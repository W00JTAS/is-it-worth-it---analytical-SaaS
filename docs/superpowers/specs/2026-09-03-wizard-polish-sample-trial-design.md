# Wizard polish + sample-trial entry point — design spec

Status: **approved** (2026-09-03, via interactive brainstorming, following the user's live screenshots
of `UploadStep` and `MappingStep`).

## Context

The user ran the app on their own catalog (`supplier_z_cenami_i_ean.csv`, 115k rows) at their actual
monitor resolution (2560-wide) and reported concrete problems, with two screenshots attached:

- `AppShell`'s collapsed sidebar hides the "IS IT WORTH IT" title completely instead of leaving a
  compact mark.
- Every screen assumes a narrow/portrait-ish viewport (`max-w-md`, `max-w-3xl`) inherited from a
  design pattern used in an unrelated project — this app's real users are on normal widescreen
  monitors, not narrow or vertically-oriented ones.
- `UploadStep` shows the chosen filename twice (once inside the native file input, once in a `<p>`
  below it).
- `MappingStep`'s native `<select>` popups are almost unreadable in dark mode (screenshot shows
  near-invisible option text) — no `color-scheme` is set anywhere in `index.css`, so the browser
  renders the native option list in light UA colors regardless of the app's dark theme.
- `MappingStep` requires an explicit "Odśwież podgląd" click after changing a mapping dropdown; the
  user wants it to refresh automatically.
- `MappingStep`'s warnings list (`Row N: zero price, skipped`, paginated 10/page) and the "Przykładowe
  wiersze" sample table both need more room — the table currently needs horizontal scrolling, and the
  whole step needs vertical scrolling, neither of which should be necessary at 2560×1440.
- `ScopeEstimateStep` exposes "Limit współbieżności" and "Próg nieświeżości" as always-visible number
  inputs with jargon labels a non-technical user won't understand; the cost/result box is cramped.
- The user wants a **zero-setup trial path**: from the very first screen, without uploading anything,
  pick one of three product categories (kitchen/AGD, toys, electronics) and run a real scan against a
  small, real, pre-built sample — so anyone can see the tool work without owning a catalog file yet.

This phase fixes all of the above, scoped to `AppShell`, `UploadStep`, `MappingStep`,
`ScopeEstimateStep`, and the shared `PaginatedList`. It does **not** touch `ProgressStep`, `ReportStep`,
column-mapping/scan business logic, or any backend endpoint — the sample-trial feature reuses the
existing `POST /scans` CSV pipeline unmodified.

## Decisions

| Topic | Decision |
|---|---|
| Design tools | Checked `mcp__21st__search` for a category-picker and a logo-reveal component before hand-building either. Nothing fit: the catalog's matches are all built around Motion-driven glow/gradient/cinematic-blur effects, which clash with this app's flat, zero-radius, monospace design language. Both are hand-built with existing primitives/Tailwind instead — see below. |
| Target viewport | Design for a normal widescreen desktop monitor (reference: 2560×1440) as the primary target, not a narrow/tall one. Containers grow from `max-w-md`/`max-w-3xl` to widths that use that space (`max-w-2xl` for single-column forms, `max-w-6xl` for the two-column `MappingStep`), but never go full-bleed edge-to-edge. |
| Sidebar title | "IS IT WORTH IT" becomes three parts: a static `IS`, a static `?`, and an animated middle (`IT WORTH IT`) that collapses to width 0 when the sidebar is icon-only and expands on hover — collapsed state reads `IS?`, expanded reads `IS IT WORTH IT?` (note: a `?` is added; today's title has none). Pure CSS (`grid-template-columns: 0fr → 1fr` transition), driven by the same `group-data-[collapsible=icon]:` variant every other sidebar element already uses — no new JS state. |
| Native `<select>` dark mode | Add `color-scheme: light;` to `:root` and `color-scheme: dark;` to `.dark` in `index.css`. This is a browser-level hint that makes native form controls (the `<select>` popup specifically) render in the browser's own dark UI colors instead of defaulting to light, fixing the unreadable-options bug everywhere a native select exists, not just `MappingStep`. Two lines, no component swap — `MappingStep` keeps its native `<select>` per the standing repo rule (RTL tests depend on it). |
| `MappingStep` auto-refresh | Replace the manual "Odśwież podgląd" button with a debounced (400ms) auto-trigger on any mapping-field change, reusing the existing `previewRequestIdRef` staleness guard unchanged (it already handles a superseded in-flight request; debouncing just reduces how often a request is fired). |
| `MappingStep` layout | Two-column grid at `lg:` breakpoint and up: left column (fields + parsed-count + warnings, `lg:w-96` fixed) and right column (sample-rows table, flexible width) inside a `max-w-6xl` shell. Below `lg:`, stays single-column (today's stacked layout) — no regression on narrow viewports, just not the primary target. |
| Warnings list columns | `PaginatedList` gains an optional `columns?: number` prop (default `1`, fully backward compatible — `ScopeEstimateStep`'s existing call site is untouched). `MappingStep`'s call site passes `columns={2}`, rendering the 10 items/page as 2 columns of 5 via CSS grid (`grid-flow-col`, explicit row count `Math.ceil(pageSize / columns)`), not a naive left-to-right wrap. |
| `ScopeEstimateStep` jargon | "Limit współbieżności" and "Próg nieświeżości" move behind a new `Collapsible` ("Ustawienia zaawansowane", collapsed by default) with one-sentence plain-language help text under each field. Defaults are unchanged (concurrency 5, staleness 14 days) — an ordinary user never has to open it. Adds the `collapsible` shadcn component (`npx shadcn add collapsible`) — per the repo's shadcn-preset rule, the bare-`data-*` grep check runs after, though the project's `PostToolUse` hook already covers this automatically. |
| Sample-trial entry point | `UploadStep` gains a second section below the existing upload form: three cards (Kuchnia i AGD / Zabawki / Elektronika), each a plain bordered `bg-card` block matching the app's existing visual language — no 21st component, see above. Clicking one fetches a pre-bundled static CSV, wraps it in a `File`, and calls a new `onSampleSelected(file, mapping)` prop — skipping `MappingStep` entirely, since the mapping for these files is fixed and known in advance. |
| Sample data source | The 3 sample CSVs are real rows filtered out of the repo's own `supplier_z_cenami_i_ean.csv` by category prefix (`AGD - Produkty` / `(Gry i zabawki)` / a fixed list of electronics category prefixes), price > 0, non-empty EAN and name, `random.Random(42).sample(..., 25)` for a reproducible pick. Same header shape as the source (`SKU;ean;nazwa;kategoria;cena`), so the deterministic `ColumnMapping` the frontend hard-codes for these files is exactly `{name: "nazwa", wholesale_price: "cena", ean: "ean", category: "kategoria", sku: "SKU"}`. Committed as static files under `frontend/public/samples/`. |
| Sample-trial scope default | The sample flow lands in `ScopeEstimateStep` with `scopeType` defaulted to **`full`**, not `sample`. Each sample CSV already contains exactly the intended 25 rows, and because rows were pooled from many different literal `kategoria` values (e.g. kitchen's 25 rows span ~20 distinct sub-categories like "Czajniki elektryczne", "Frytownice"), the app's *"Próbka per kategoria"* scope type would mostly-or-fully degenerate to the same 25 rows anyway, for the wrong reason (many 1-2-row "categories", not a deliberate per-category sample). `full` on a 25-row file is simpler, has no edge cases, and is exactly "run a real scan on 25 real products" as asked. Nothing about `ScopeEstimateStep` is locked or hidden for this entry path — the user can still change scope type if they want to. |
| Provider used for the sample scan | Whatever `PROVIDER` the backend is already configured with (e.g. `groq+firecrawl`, per `.claude/rules/groq-compound-free-tier-reliability.md`) — the sample-trial feature does not add per-request provider selection; it exists to let someone try the *currently configured* pipeline, not to add a new provider-choice UI. |

## `AppShell` title reveal

`AppShell.tsx`'s `SidebarHeader` span changes from:

```tsx
<span className="px-2 py-1 text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">IS IT WORTH IT</span>
```

to a three-part structure that is **always rendered** (no `hidden` variant on the outer element):

```tsx
<span className="flex items-baseline overflow-hidden px-2 py-1 text-sm font-semibold tracking-tight">
  <span>IS</span>
  <span className="grid grid-cols-[1fr] transition-[grid-template-columns] duration-200 ease-linear group-data-[collapsible=icon]:grid-cols-[0fr]">
    <span className="min-w-0 overflow-hidden whitespace-nowrap">{' IT WORTH IT'}</span>
  </span>
  <span>?</span>
</span>
```

The middle `grid` wrapper is the standard CSS "animate to auto width" technique: a 1-column grid track
transitioning between `0fr` and `1fr` animates smoothly (unlike `width: 0 → auto`, which cannot
transition), and the inner `overflow-hidden`+`min-w-0` child clips content that hasn't grown into view
yet. `group-data-[collapsible=icon]:` is the exact bracketed-variant form every other sidebar element
in this codebase already uses (see `.claude/rules/frontend-ui.md`) — critical to get right, since the
bare form (`data-collapsible-icon:`) silently no-ops.

## `PaginatedList` column support

```ts
interface PaginatedListProps<T> {
  items: readonly T[]
  pageSize: number
  renderItem: (item: T, index: number) => ReactNode
  emptyState?: ReactNode
  columns?: number   // default 1, backward compatible
}
```

When `columns > 1`, the `<ul>` becomes a CSS grid: `grid-flow-col` (column-major fill, so items 0-4
fill the left column top-to-bottom and items 5-9 fill the right column, matching "5 left, 5 right"
literally) with an explicit row count via inline style, since Tailwind has no arbitrary-row-count
utility that takes a runtime value cleanly:

```tsx
const rows = columns > 1 ? Math.ceil(pageItems.length / columns) : undefined
// ...
<ul
  className={columns > 1 ? 'grid grid-flow-col gap-x-6 gap-y-1' : 'space-y-1'}
  style={rows ? { gridTemplateRows: `repeat(${rows}, minmax(0, auto))` } : undefined}
>
```

## Sample CSV generation (one-off, run once, output committed)

Run from the repo root once, output committed as static assets — not a permanent script:

```python
import csv
import random

KITCHEN_PREFIX = 'AGD - Produkty'
TOY_PREFIX = '(Gry i zabawki)'
ELECTRONICS_PREFIXES = (
    'Telefony komórkowe', 'Notebooki', 'Monitory', 'Peryferia',
    'Dyski i akcesoria', 'Karty graficzne', 'Pamięci', 'Zasilanie awaryjne',
    'CCTV IP', 'Komunikacja i łączność', 'Obudowy i zasilacze',
)

def matches(cat, prefix_or_tuple):
    if isinstance(prefix_or_tuple, tuple):
        return any(cat.startswith(p) for p in prefix_or_tuple)
    return cat.startswith(prefix_or_tuple)

buckets = {'kuchnia': [], 'zabawki': [], 'elektronika': []}
with open('supplier_z_cenami_i_ean.csv', newline='', encoding='utf-8') as f:
    r = csv.DictReader(f, delimiter=';')
    for row in r:
        cat = row['kategoria']
        try:
            price_ok = float(row['cena'].replace(',', '.')) > 0
        except (ValueError, AttributeError):
            price_ok = False
        if not price_ok or not row['ean'].strip() or not row['nazwa'].strip():
            continue
        if matches(cat, KITCHEN_PREFIX):
            buckets['kuchnia'].append(row)
        elif matches(cat, TOY_PREFIX):
            buckets['zabawki'].append(row)
        elif matches(cat, ELECTRONICS_PREFIXES):
            buckets['elektronika'].append(row)

FIELDNAMES = ['SKU', 'ean', 'nazwa', 'kategoria', 'cena']
for name, rows in buckets.items():
    sample = random.Random(42).sample(rows, 25)
    with open(f'frontend/public/samples/{name}.csv', 'w', newline='', encoding='utf-8') as out:
        w = csv.DictWriter(out, fieldnames=FIELDNAMES, delimiter=';', quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(sample)
```

Verified live (2026-09-03): candidate pools are 9115 (kuchnia) / 2547 (zabawki) / 12523 (elektronika)
rows — comfortably large enough for a stable `random.Random(42)` sample of 25 each.

## Testing

- `AppShell`: existing tests untouched (they don't assert on the title text); add one new test that
  the title text content is `IS?` — reachable via `textContent`, since the `?`/`IT WORTH IT` split
  across three `<span>`s means no single node has the full string.
- `PaginatedList`: new test for `columns={2}` — 10 items render as 2 grid columns, items 0-4 in
  document order before items 5-9 (column-major, not row-major).
- `UploadStep`: existing "shows the chosen file name" test is **deleted** (the behavior it tests is
  being removed) — the other two existing tests (button disabled/enabled, `onFileSelected` called with
  the file) are untouched. New tests for the three sample cards: clicking one calls `onSampleSelected`
  with a `File` whose content matches the fetched CSV and the fixed `ColumnMapping`.
- `MappingStep`: existing tests updated to drop `userEvent.click`-ing "Odśwież podgląd" (button no
  longer exists) in favor of asserting `getCsvPreview` is called again after a field change once the
  debounce timer fires (`vi.useFakeTimers()` / `vi.advanceTimersByTime(400)`, consistent with any
  existing timer-based test pattern already in the suite).
- `ScopeEstimateStep`: existing tests updated only where they query the now-collapsed
  concurrency/staleness inputs — wrap those queries in "open the Collapsible first" (`userEvent.click`
  on the "Ustawienia zaawansowane" trigger), same adaptation pattern Phase 6b used for the `Select`
  swap. No coverage dropped.
- `npm run build` (`tsc -b`) remains mandatory per the standing project rule — `MappingStep`'s grid
  layout and `PaginatedList`'s new prop both touch typed component boundaries.
- Manual verification in both light and dark mode is required specifically for the `color-scheme` fix
  (native select popups aren't reliably testable via jsdom/RTL — this is a real-browser check, not a
  unit test).

## Out of scope for this phase

- `ProgressStep`, `ReportStep` — untouched, not mentioned in the user's feedback.
- Any backend change — the sample-trial feature deliberately reuses `POST /csv/preview` /
  `POST /scans` exactly as they exist today; `MappingStep` is skipped client-side only, the backend
  never knows the mapping came from a preset rather than a user's dropdown choices.
- Per-request provider selection for the sample scan (uses whatever `PROVIDER` the backend already
  has configured).
- Locking/disabling `ScopeEstimateStep`'s controls when arriving via the sample-trial path — the user
  can freely change scope type, delivery days, etc. after landing there.
- A 4th+ sample category, or letting the user pick sample size — fixed at 3 categories × 25 products,
  matching exactly what was asked for.
