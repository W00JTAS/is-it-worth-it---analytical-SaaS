"""Reusable eval harness for comparing PriceProvider backends on a fixed,
reproducible product sample from the real catalog CSV.

This exists because the 2026-08-28 Groq spike (22% success, 23 products) was
run ad hoc and left no reusable script or fixed sample behind — see
`.claude/rules/groq-compound-free-tier-reliability.md`. The sample this script
draws is NOT the same 23 products from that spike (they were never recorded);
it is a new, seeded, on-disk sample so every future run of this script is
directly comparable to every other one.

Usage (from `backend/`, after sourcing ../.env.local per README.md):

    set -a && source ../.env.local && set +a
    .venv/bin/python scripts/provider_eval.py --provider groq-compound-mini
    .venv/bin/python scripts/provider_eval.py --provider groq-compound
    .venv/bin/python scripts/provider_eval.py --provider gemini --debug-raw   # first: inspect one raw response
    .venv/bin/python scripts/provider_eval.py --provider gemini

`gemini` requires `GEMINI_API_KEY` and `pip install google-genai` (not a
project dependency — this is spike tooling, not shipped code).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.product import Product  # noqa: E402
from app.providers.base import OfferResult, ProviderUnavailable  # noqa: E402
from app.providers.groq import GroqProvider  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = SCRIPT_DIR / "eval_samples"
RESULTS_DIR = SCRIPT_DIR / "eval_results"
DEFAULT_CSV = SCRIPT_DIR.parent.parent / "supplier_z_cenami_i_ean.csv"


def load_catalog(csv_path: Path) -> list[Product]:
    """Loads the supplier CSV with an explicit dialect — never csv.Sniffer,
    see .claude/rules/money.md ("csv.Sniffer cannot be trusted for
    doublequote"). Rows with wholesale_price "0.00" are dropped: that's the
    supplier's price-on-request marker, not a real product to look up
    (same rule file, "'0.00' is a marker, not a price").
    """
    products: list[Product] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";", quotechar='"', doublequote=True)
        for row in reader:
            price_raw = (row.get("cena") or "").strip()
            try:
                price = Decimal(price_raw)
            except InvalidOperation:
                continue
            if price <= 0:
                continue
            name = (row.get("nazwa") or "").strip()
            if not name:
                continue
            products.append(Product(
                tenant_id="eval",
                source="csv",
                external_id=(row.get("SKU") or "").strip(),
                variant_id=None,
                name=name,
                ean=(row.get("ean") or "").strip() or None,
                wholesale_price=price,
                currency="PLN",
                category=(row.get("kategoria") or "").strip(),
            ))
    return products


def sampled_products(csv_path: Path, n: int, seed: int) -> list[Product]:
    """Returns the same n products every time for a given (csv_path, n, seed)
    by persisting the sampled SKUs to disk on first draw. Every later run —
    regardless of which provider or how much later — reads back that same
    file, so different providers are always compared on identical inputs.
    """
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    sample_file = SAMPLES_DIR / f"sample_seed{seed}_n{n}.json"

    catalog = load_catalog(csv_path)
    by_sku = {p.external_id: p for p in catalog}

    if sample_file.exists():
        skus = json.loads(sample_file.read_text())
        missing = [s for s in skus if s not in by_sku]
        if missing:
            raise SystemExit(
                f"{sample_file} references {len(missing)} SKU(s) no longer in "
                f"{csv_path} (e.g. {missing[0]!r}) — catalog changed underneath "
                f"the fixed sample. Delete the sample file to redraw."
            )
        return [by_sku[s] for s in skus]

    rng = random.Random(seed)
    chosen = rng.sample(catalog, n)
    sample_file.write_text(json.dumps([p.external_id for p in chosen], indent=2))
    return chosen


class GeminiSearchClient:
    """Spike-only wrapper around Google's `google-genai` SDK using the
    Interactions API (`client.interactions.create`), grounded with the
    `google_search` tool. NOT wired into app.providers — this is
    unvalidated: the exact response shape for combining grounding with a
    JSON schema is not confirmed in Google's docs as of 2026-08-28 (only a
    prose claim for Gemini 3, which does not have a no-card free tier — see
    groq-alternatives-research.md), so this asks for JSON via the prompt
    instead of a schema, and parses defensively. Run with --debug-raw once
    before trusting the parser at scale.
    """

    MODEL = "gemini-3.6-flash"

    def __init__(self, api_key: str):
        from google import genai  # local import: optional dependency
        self._client = genai.Client(api_key=api_key)

    def raw_call(self, prompt: str):
        return self._client.interactions.create(
            model=self.MODEL,
            input=prompt,
            tools=[{"type": "google_search"}],
        )

    def find_cheapest(
        self, product: Product, market: str, max_delivery_days: int
    ) -> OfferResult | None:
        prompt = self._build_prompt(product, market, max_delivery_days)
        try:
            interaction = self.raw_call(prompt)
        except Exception as exc:  # noqa: BLE001 — spike script, classify broadly
            raise ProviderUnavailable(str(exc)) from exc

        text = self._extract_text(interaction)
        if not text:
            return None

        parsed = self._extract_json(text)
        if not isinstance(parsed, dict) or not parsed.get("found"):
            return None

        from app.providers.parsing import validate_offer_fields
        return validate_offer_fields(
            parsed,
            raw_response=text,
            citations=(),
            max_delivery_days=max_delivery_days,
        )

    def _build_prompt(self, product: Product, market: str, max_delivery_days: int) -> str:
        ean_part = f" (EAN: {product.ean})" if product.ean else ""
        return (
            f'Search the web for the cheapest real, currently-buyable offer for the product '
            f'"{product.name}"{ean_part} in the {market} market, from a seller that can deliver '
            f"within {max_delivery_days} days.\n\n"
            "Respond with ONLY a single JSON object (no markdown fences, no other text) with "
            'exactly these keys: "found" (boolean), "price" (number), "currency" (string), '
            '"seller" (string), "source_url" (string), "delivery_days" (integer), '
            '"confidence" (number 0-1). Set "found" to false if you cannot find a genuine '
            f"current offer, or if the only offer you found has delivery_days greater than "
            f"{max_delivery_days}."
        )

    @staticmethod
    def _extract_text(interaction) -> str | None:
        outputs = getattr(interaction, "outputs", None) or []
        for output in outputs:
            if getattr(output, "type", None) == "text":
                text = getattr(output, "text", None)
                if text:
                    return text
        # Fallback: recursively hunt for the longest string value anywhere in
        # the object, in case the shape differs from the documented example.
        try:
            dumped = interaction.model_dump()
        except AttributeError:
            return None
        candidates: list[str] = []

        def walk(node):
            if isinstance(node, str):
                candidates.append(node)
            elif isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(dumped)
        return max(candidates, key=len) if candidates else None

    @staticmethod
    def _extract_json(text: str) -> object | None:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def build_provider(name: str):
    if name == "groq-compound-mini":
        return GroqProvider(api_key=os.environ["GROQ_API_KEY"])
    if name == "groq-compound":
        return GroqProvider(api_key=os.environ["GROQ_API_KEY"], search_model="groq/compound")
    if name == "gemini":
        return GeminiSearchClient(api_key=os.environ["GEMINI_API_KEY"])
    raise SystemExit(f"unknown provider {name!r}")


def run_eval(
    provider, products: list[Product], market: str, max_delivery_days: int, delay_seconds: float,
) -> list[dict]:
    results = []
    for i, product in enumerate(products, 1):
        print(f"[{i}/{len(products)}] {product.name!r} ... ", end="", flush=True)
        entry: dict = {"sku": product.external_id, "name": product.name, "ean": product.ean}
        try:
            offer = provider.find_cheapest(product, market=market, max_delivery_days=max_delivery_days)
        except Exception as exc:  # noqa: BLE001 — classify every failure mode, don't crash the batch
            entry["outcome"] = "error"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            print(f"ERROR ({type(exc).__name__})")
        else:
            if offer is None:
                entry["outcome"] = "not_found"
                print("not found")
            else:
                entry["outcome"] = "found"
                entry["offer"] = {k: str(v) if isinstance(v, Decimal) else v
                                   for k, v in asdict(offer).items() if k != "raw_response"}
                print(f"FOUND {offer.price} {offer.currency} @ {offer.seller}")
        results.append(entry)
        if i < len(products):
            time.sleep(delay_seconds)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", required=True, choices=["groq-compound-mini", "groq-compound", "gemini"])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--market", default="PL")
    parser.add_argument("--max-delivery-days", type=int, default=5)
    parser.add_argument("--delay-seconds", type=float, default=3.0,
                         help="pause between calls; conservative default since free-tier RPM isn't confirmed for every provider")
    parser.add_argument("--debug-raw", action="store_true",
                         help="gemini only: print one raw interaction object and exit, before running the batch")
    args = parser.parse_args()

    products = sampled_products(args.csv, args.sample_size, args.seed)
    provider = build_provider(args.provider)

    if args.debug_raw:
        if args.provider != "gemini":
            raise SystemExit("--debug-raw is only meaningful for --provider gemini")
        interaction = provider.raw_call(provider._build_prompt(products[0], args.market, args.max_delivery_days))
        try:
            print(json.dumps(interaction.model_dump(), indent=2, default=str))
        except AttributeError:
            print(repr(interaction))
        return

    results = run_eval(provider, products, args.market, args.max_delivery_days, args.delay_seconds)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RESULTS_DIR / f"{args.provider}_seed{args.seed}_n{args.sample_size}_{int(time.time())}.json"
    out_file.write_text(json.dumps(results, indent=2))

    found = sum(1 for r in results if r["outcome"] == "found")
    not_found = sum(1 for r in results if r["outcome"] == "not_found")
    errored = sum(1 for r in results if r["outcome"] == "error")
    total = len(results)
    print(f"\n{args.provider}: {found}/{total} found, {not_found}/{total} not found, "
          f"{errored}/{total} error ({found / total:.0%} success)")
    print(f"Results written to {out_file}")


if __name__ == "__main__":
    main()
