// Browser-based verification of every `found` offer from a provider_eval.py
// run: opens each offer's source_url in a real browser (curl/WebFetch get
// 403'd by Allegro and other bot-gated stores) and dumps what's actually on
// the page, so a human/agent can check product match, price match, and (for
// marketplace/aggregator pages) whether a lower price is visible elsewhere
// on the same page.
//
// This script does NOT judge correctness itself — it fetches ground truth.
// Judging (does the page text actually match the claimed price/product) is
// a manual step done by reading each result's `text` field.
//
// Setup:
//   npm install playwright   (or point PLAYWRIGHT_MODULE at an existing install)
//   npx playwright install chromium   (unless CHROME_PATH points at a system Chrome)
//
// Env vars (both optional):
//   PLAYWRIGHT_MODULE  — module specifier/path to import `chromium` from.
//                         Defaults to the plain `playwright` package.
//   CHROME_PATH        — path to a Chrome/Chromium executable. When unset,
//                         Playwright's own bundled Chromium is used.
//
// Usage (from backend/):
//   node scripts/verify_offers_browser.mjs <found_offers.json> <out.json>
//
// <found_offers.json> is an array of {sku, name, price, currency, seller, url}
// — extract it from a provider_eval.py --keep-raw result file's `found`
// entries first (offer.price/currency/seller/source_url).

import { readFileSync, writeFileSync } from 'fs';

const playwrightModule = process.env.PLAYWRIGHT_MODULE || 'playwright';
const { chromium } = await import(playwrightModule);

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('Usage: node verify_offers_browser.mjs <found_offers.json> <out.json>');
  process.exit(1);
}

const offers = JSON.parse(readFileSync(inPath, 'utf8'));

const REJECT_SELECTORS = [
  'button:has-text("Odrzuć")', 'button:has-text("Odrzucam")',
  'button:has-text("Reject")', 'button:has-text("Nie zgadzam")',
  'button:has-text("Tylko niezbędne")', 'button:has-text("Only necessary")',
  '#onetrust-reject-all-handler', 'button[aria-label*="reject" i]',
];

async function tryRejectCookies(page) {
  for (const sel of REJECT_SELECTORS) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.isVisible({ timeout: 1000 })) {
        await btn.click({ timeout: 2000 });
        await page.waitForTimeout(300);
        return true;
      }
    } catch {}
  }
  return false;
}

const launchOptions = { headless: true };
if (process.env.CHROME_PATH) {
  launchOptions.executablePath = process.env.CHROME_PATH;
}
const browser = await chromium.launch(launchOptions);
const results = [];

for (const offer of offers) {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
    viewport: { width: 1400, height: 1000 },
  });
  const page = await context.newPage();
  const record = {
    sku: offer.sku, name: offer.name, extracted_price: offer.price,
    currency: offer.currency, seller: offer.seller, url: offer.url,
  };
  try {
    const resp = await page.goto(offer.url, { waitUntil: 'networkidle', timeout: 25000 });
    record.http_status = resp ? resp.status() : null;
    await tryRejectCookies(page);
    await page.waitForTimeout(1000);
    const bodyText = await page.evaluate(() => document.body.innerText).catch(() => '');
    record.title = await page.title().catch(() => '');
    record.text_length = bodyText.length;
    // Full text, never truncated — a wrong/fabricated price can appear
    // anywhere on the page, not just the first screen's worth.
    record.text = bodyText;
    const lower = bodyText.toLowerCase();
    record.likely_blocked = /captcha|access denied|are you a human|attention required|cloudflare|robot or human/.test(lower) && bodyText.length < 2000;
  } catch (err) {
    record.error = String(err.message || err);
  }
  await context.close();
  results.push(record);
  console.log(`done: ${record.sku} status=${record.http_status ?? 'ERR'} len=${record.text_length ?? 0} blocked=${record.likely_blocked ?? 'n/a'}`);
  writeFileSync(outPath, JSON.stringify(results, null, 2), 'utf8');
}

await browser.close();
console.log('ALL DONE');
