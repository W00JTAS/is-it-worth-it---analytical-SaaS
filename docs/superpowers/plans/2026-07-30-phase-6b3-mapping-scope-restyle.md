# Phase 6b-3 — Mapping + Scope+Estimate restyle — Implementation Plan

**Goal:** Restyle `MappingStep` and `ScopeEstimateStep` onto the shadcn/token system, replacing their
unbounded warning lists with `PaginatedList` (10/page), and fixing the reported unstyled-input/
low-contrast defects. No change to either screen's logic, validation, or API calls.

**Architecture:** Same re-skin approach as Phase 6b-2, with one deliberate deviation from the Phase 6b
spec's literal "native `<select>` → shadcn `Select`" mapping: **Mapping's 5 dropdowns stay native
`<select>` elements**, restyled with Tailwind classes matching the token system, rather than being
swapped for shadcn's Radix-based `Select`. Reason: `MappingStep.test.tsx` has several hard-won
regression tests (explicitly commented "Fix 2/3, final whole-branch review" — an in-flight-request
guard and a don't-revert-user-edits guard from Phase 5c) built on `userEvent.selectOptions()` and
`toHaveValue()`, both native-`<select>`-specific APIs that do not work against Radix's `Select` (a
button + portal-rendered listbox, not a real `<select>`). Rewriting those tests to a click-based
interaction model is a real risk to real, valuable regression coverage, for a component that's a
single row of paired label+dropdown — not worth it. `ScopeEstimateStep`'s radio buttons and number
inputs DO become shadcn `RadioGroup`/`Input` — their tests are click-based (`userEvent.click`), which
works identically against Radix primitives, so there's no equivalent risk there.

**Tech Stack:** React 19, shadcn/ui, `PaginatedList` (Phase 6b-1), Vitest + React Testing Library.

## Global Constraints

- Implements the relevant slice of `docs/superpowers/specs/2026-07-30-phase-6b-per-screen-restyle-design.md`,
  **with the native-`<select>` deviation documented above** — this is a controller-made implementation
  decision serving the spec's actual intent (fix the visual bug, adopt the token system), not a
  departure from it.
- No change to either screen's logic, props, validation, or API call shapes.
- `npm run build` required on every task, alongside `npm test`.
- `PaginatedList`'s props are exactly `{ items, pageSize, renderItem, emptyState? }` (Phase 6b-1) —
  both warning lists use `pageSize={10}`.
- Any existing test depending on markup/interaction details that changed must be updated to match,
  never weakened or deleted.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/ui/table.tsx`, `radio-group.tsx` | New shadcn components |
| `frontend/src/steps/MappingStep.tsx` | Modified: shadcn `Button`/`Table`, `PaginatedList` for warnings, restyled native `<select>`s, semantic tokens |
| `frontend/src/steps/ScopeEstimateStep.tsx` | Modified: shadcn `Button`/`Input`/`RadioGroup`/`Label`, `PaginatedList` for warnings, semantic tokens |

---

### Task 1: Restyle `MappingStep`

**Files:**
- Create: `frontend/src/components/ui/table.tsx` (via `npx shadcn add table`)
- Modify: `frontend/src/steps/MappingStep.tsx`

**Interfaces:**
- Consumes: `Button` (Phase 6a), `PaginatedList` (Phase 6b-1, exact props `{ items, pageSize,
  renderItem, emptyState? }`), `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableHead`/`TableCell`
  (this task).
- Produces: no change to `MappingStepProps` (`{ file: File; onConfirmed: (mapping: ColumnMapping) =>
  void }`).

- [ ] **Step 1: Install the shadcn table component**

```bash
cd frontend && npx shadcn add table
```

- [ ] **Step 2: Replace `MappingStep.tsx`'s content**

```tsx
import { useCallback, useEffect, useRef, useState } from 'react'
import { getCsvPreview } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CsvPreview } from '../api/types'
import { Button } from '@/components/ui/button'
import { PaginatedList } from '@/components/PaginatedList'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const EMPTY_MAPPING: ColumnMapping = {
  name: null,
  wholesale_price: null,
  ean: null,
  category: null,
  sku: null,
}

const SELECT_CLASS =
  'h-9 w-56 rounded-md border border-input bg-transparent px-3 py-1 text-sm text-foreground shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30'

interface MappingStepProps {
  file: File
  onConfirmed: (mapping: ColumnMapping) => void
}

export function MappingStep({ file, onConfirmed }: MappingStepProps) {
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const previewRequestIdRef = useRef(0)

  const loadPreview = useCallback(async (override?: ColumnMapping) => {
    const requestId = ++previewRequestIdRef.current
    setError(null)
    setIsLoading(true)
    try {
      const result = await getCsvPreview(file, override)
      if (previewRequestIdRef.current === requestId) {
        setPreview(result)
        if (override === undefined) {
          setMapping(result.mapping)
        }
      }
    } catch (err) {
      if (previewRequestIdRef.current === requestId) {
        setError(err instanceof ApiError ? err.message : 'Nie udało się wczytać podglądu pliku')
      }
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }, [file])

  useEffect(() => {
    loadPreview()
  }, [loadPreview])

  function handleFieldChange(field: keyof ColumnMapping, value: string) {
    setMapping({ ...mapping, [field]: value || null })
  }

  function handleRefresh() {
    loadPreview(mapping)
  }

  const requiredFilled = Boolean(
    mapping.name && mapping.wholesale_price && mapping.ean && mapping.category,
  )

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-12 p-8">
      <h1 className="text-xl font-semibold text-foreground">Mapowanie kolumn</h1>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {preview && (
        <>
          <section className="flex flex-col gap-4">
            <div className="divide-y divide-border rounded-2xl border border-border bg-card">
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Nazwa
                <select
                  value={mapping.name ?? ''}
                  onChange={(e) => handleFieldChange('name', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Cena hurtowa
                <select
                  value={mapping.wholesale_price ?? ''}
                  onChange={(e) => handleFieldChange('wholesale_price', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                EAN
                <select
                  value={mapping.ean ?? ''}
                  onChange={(e) => handleFieldChange('ean', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Kategoria
                <select
                  value={mapping.category ?? ''}
                  onChange={(e) => handleFieldChange('category', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                SKU (opcjonalne)
                <select
                  value={mapping.sku ?? ''}
                  onChange={(e) => handleFieldChange('sku', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— brak —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
            </div>
            <Button type="button" onClick={handleRefresh} disabled={isLoading} className="self-start">
              Odśwież podgląd
            </Button>
          </section>

          <section className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>
              {preview.parsed_count} / {preview.total_rows} wierszy sparsowanych poprawnie
            </p>
            {preview.warnings.length > 0 && (
              <PaginatedList
                items={preview.warnings}
                pageSize={10}
                renderItem={(warning) => <span className="text-warning">{warning}</span>}
              />
            )}
            {preview.warning_count > preview.warnings.length && (
              <p>...i {preview.warning_count - preview.warnings.length} więcej</p>
            )}
          </section>

          {preview.sample_rows.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Przykładowe wiersze</h2>
              <Table>
                <TableHeader>
                  <TableRow>
                    {preview.headers.map((h) => (
                      <TableHead key={h}>{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.sample_rows.map((row, i) => (
                    <TableRow key={i}>
                      {preview.headers.map((h) => (
                        <TableCell key={h}>{row[h] ?? ''}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          )}

          <Button
            type="button"
            onClick={() => onConfirmed(mapping)}
            disabled={!requiredFilled || isLoading}
            className="self-start"
          >
            Dalej
          </Button>
        </>
      )}
    </div>
  )
}
```

Note: this drops the `list-disc`/bullet styling the old `<ul>` had — `PaginatedList` renders a plain
`<ul>` with no bullet markers, matching the flat/hairline aesthetic already established for the rest
of this design system (Report's category table, scenario matrix, etc. use no bullets either). This is
a deliberate visual choice, not an oversight.

- [ ] **Step 3: Run `MappingStep`'s existing test suite**

```bash
npm test -- MappingStep
```

Expected: PASS, all 8 existing tests unchanged. Verify specifically:
- `getByLabelText('Nazwa')`/etc. + `.toHaveValue(...)` still work — the `<select>` elements are
  unchanged in kind, only their className and the wrapping div's classes changed.
- `userEvent.selectOptions(...)` still works for the same reason.
- The "shows truncated warnings with a remaining count" test (1 warning, `warning_count: 22`) still
  finds `'Row 2: missing name, skipped'` (rendered inside `PaginatedList`, which shows everything when
  `items.length <= pageSize`) and `'...i 21 więcej'` (rendered by the separate remainder paragraph,
  unrelated to `PaginatedList`).

If any test fails, do not weaken the assertion — investigate whether the markup change broke
something real (e.g. `PaginatedList` wraps `renderItem`'s output in its own `<li>`, so `renderItem`
must return content, not another `<li>` — verify this wasn't gotten backwards).

- [ ] **Step 4: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/table.tsx frontend/src/steps/MappingStep.tsx \
  frontend/package.json frontend/package-lock.json
git commit -m "Restyle MappingStep: shadcn Button/Table, PaginatedList warnings, tokens"
```

---

### Task 2: Restyle `ScopeEstimateStep`

**Files:**
- Create: `frontend/src/components/ui/radio-group.tsx` (via `npx shadcn add radio-group`)
- Modify: `frontend/src/steps/ScopeEstimateStep.tsx`

**Interfaces:**
- Consumes: `Button`, `Input`, `Label` (already installed), `PaginatedList` (Phase 6b-1),
  `RadioGroup`/`RadioGroupItem` (this task).
- Produces: no change to `ScopeEstimateStepProps` (`{ file: File; columnMapping: ColumnMapping;
  onStarted: (scanId: string) => void }`).

- [ ] **Step 1: Install the shadcn radio-group component**

```bash
cd frontend && npx shadcn add radio-group
```

- [ ] **Step 2: Replace `ScopeEstimateStep.tsx`'s content**

```tsx
import { useRef, useState } from 'react'
import { createScan, startScan } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CreateScanResult, ScopeType } from '../api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PaginatedList } from '@/components/PaginatedList'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'

interface ScopeEstimateStepProps {
  file: File
  columnMapping: ColumnMapping
  onStarted: (scanId: string) => void
}

// Standard Polish plural rules for "produkt": 1 -> singular, 2-4 (excluding
// 12-14) -> "few" form, everything else (0, 5+, 12-14) -> "many" form.
function pluralizeProdukt(n: number): string {
  if (n === 1) return 'produkt'
  const lastDigit = n % 10
  const lastTwo = n % 100
  if (lastDigit >= 2 && lastDigit <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return 'produkty'
  return 'produktów'
}

export function ScopeEstimateStep({ file, columnMapping, onStarted }: ScopeEstimateStepProps) {
  const [scopeType, setScopeType] = useState<ScopeType>('full')
  const [samplePerCategory, setSamplePerCategory] = useState('50')
  const [maxDeliveryDays, setMaxDeliveryDays] = useState(5)
  const [maxConcurrency, setMaxConcurrency] = useState(5)
  const [stalenessThresholdDays, setStalenessThresholdDays] = useState(14)
  const [result, setResult] = useState<CreateScanResult | null>(null)
  const [forceRefreshStale, setForceRefreshStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isEstimating, setIsEstimating] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const estimateRequestIdRef = useRef(0)
  const fieldsDisabled = isEstimating || isStarting

  function clearStaleEstimate() {
    setResult(null)
    setForceRefreshStale(false)
  }

  function handleScopeTypeChange(next: ScopeType) {
    clearStaleEstimate()
    setScopeType(next)
  }

  function handleSamplePerCategoryChange(value: string) {
    clearStaleEstimate()
    setSamplePerCategory(value)
  }

  function handleMaxDeliveryDaysChange(value: number) {
    clearStaleEstimate()
    setMaxDeliveryDays(value)
  }

  function handleMaxConcurrencyChange(value: number) {
    clearStaleEstimate()
    setMaxConcurrency(value)
  }

  function handleStalenessThresholdChange(value: number) {
    clearStaleEstimate()
    setStalenessThresholdDays(value)
  }

  async function handleEstimate() {
    const requestId = ++estimateRequestIdRef.current
    setError(null)
    setIsEstimating(true)
    try {
      const created = await createScan(
        file,
        {
          scopeType,
          samplePerCategory: scopeType === 'sample' ? Number(samplePerCategory) : undefined,
          market: 'PL',
          maxDeliveryDays,
          maxConcurrency,
          stalenessThresholdDays,
        },
        columnMapping,
      )
      if (estimateRequestIdRef.current === requestId) {
        setResult(created)
      }
    } catch (err) {
      if (estimateRequestIdRef.current === requestId) {
        setError(err instanceof ApiError ? err.message : 'Nie udało się oszacować kosztu')
      }
    } finally {
      if (estimateRequestIdRef.current === requestId) {
        setIsEstimating(false)
      }
    }
  }

  async function handleStart() {
    if (!result) return
    setError(null)
    setIsStarting(true)
    try {
      await startScan(result.scan_id, forceRefreshStale)
      onStarted(result.scan_id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się uruchomić skanu')
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Zakres skanu</h1>

      <fieldset className="flex flex-col gap-3 text-sm text-muted-foreground">
        <RadioGroup
          value={scopeType}
          onValueChange={(value) => handleScopeTypeChange(value as ScopeType)}
          disabled={fieldsDisabled}
        >
          <div className="flex items-center gap-2">
            <RadioGroupItem value="full" id="scope-full" />
            <Label htmlFor="scope-full">Pełny skan</Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem value="sample" id="scope-sample" />
            <Label htmlFor="scope-sample">Próbka per kategoria</Label>
          </div>
        </RadioGroup>
        {scopeType === 'sample' && (
          <div className="flex flex-col gap-1 pl-6">
            <Label htmlFor="sample-per-category">Liczba produktów per kategoria</Label>
            <Input
              id="sample-per-category"
              type="number"
              min={1}
              value={samplePerCategory}
              onChange={(e) => handleSamplePerCategoryChange(e.target.value)}
              disabled={fieldsDisabled}
              className="w-24"
            />
          </div>
        )}
      </fieldset>

      <div className="flex flex-col gap-1">
        <Label htmlFor="max-delivery-days">Limit czasu dostawy (dni)</Label>
        <Input
          id="max-delivery-days"
          type="number"
          min={1}
          value={maxDeliveryDays}
          onChange={(e) => handleMaxDeliveryDaysChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="max-concurrency">Limit współbieżności</Label>
        <Input
          id="max-concurrency"
          type="number"
          min={1}
          value={maxConcurrency}
          onChange={(e) => handleMaxConcurrencyChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24"
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="staleness-threshold">Próg nieświeżości (dni)</Label>
        <Input
          id="staleness-threshold"
          type="number"
          min={0}
          value={stalenessThresholdDays}
          onChange={(e) => handleStalenessThresholdChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24"
        />
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!result && (
        <Button type="button" onClick={handleEstimate} disabled={isEstimating} className="self-start">
          Oszacuj koszt
        </Button>
      )}

      {result && (
        <div className="flex flex-col gap-3 rounded-md border border-border p-4 text-sm text-foreground">
          <p>
            Bez odświeżania:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_without_refresh} USD (~{result.estimate.seconds_without_refresh}s)
            </span>
          </p>
          <p>
            Z odświeżaniem:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_with_refresh} USD (~{result.estimate.seconds_with_refresh}s)
            </span>
          </p>
          {result.overlapping_count > 0 && (
            <p>
              {result.overlapping_count} {pluralizeProdukt(result.overlapping_count)} w tym skanie
              nakładają się z poprzednimi skanami.
            </p>
          )}
          {result.stale_count > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={forceRefreshStale}
                onChange={(e) => setForceRefreshStale(e.target.checked)}
                disabled={fieldsDisabled}
                className="accent-primary"
              />
              Odśwież nieświeże ({result.stale_count} {pluralizeProdukt(result.stale_count)} z nich nie
              sprawdzano od dawna)
            </label>
          )}
          {result.warnings.length > 0 && (
            <PaginatedList
              items={result.warnings}
              pageSize={10}
              renderItem={(warning) => <span className="text-warning">{warning}</span>}
            />
          )}
          <Button type="button" onClick={handleStart} disabled={isStarting} className="self-start">
            Uruchom skan
          </Button>
        </div>
      )}
    </div>
  )
}
```

Note: the "Odśwież nieświeże" checkbox deliberately stays a native `<input type="checkbox">` (with an
`accent-primary` Tailwind utility for on-brand checkmark color) rather than becoming shadcn's
`Checkbox` — same reasoning as Mapping's `<select>`s: it's a single, occasionally-shown control, its
test only needs `userEvent.click` (already compatible with a native checkbox), and swapping it buys
little for real restructuring risk.

- [ ] **Step 3: Run `ScopeEstimateStep`'s existing test suite**

```bash
npm test -- ScopeEstimateStep
```

Expected: PASS, all 8 existing tests unchanged. Verify specifically:
- `userEvent.click(screen.getByLabelText('Próbka per kategoria'))` correctly activates the
  `RadioGroupItem` via its paired `<Label htmlFor="scope-sample">` — Radix's radio item renders as a
  real `<button role="radio" id="scope-sample">`, and browsers (and jsdom) forward a label click to
  any element valid as a `for` target, including `<button>`.
  `RadioGroup`'s `onValueChange` fires `handleScopeTypeChange('sample')`, identical to the old
  `onChange` handler's effect.
- `getByLabelText('Pełny skan')).toBeDisabled()` / `getByLabelText('Próbka per kategoria')).toBeDisabled()`
  resolve correctly — `RadioGroup`'s `disabled` prop cascades to its items, which render a real
  `disabled` attribute on their underlying `<button>`.
- The in-flight-request-disables-everything test and the two number-input tests
  (`userEvent.clear`/`userEvent.type` on `Input`) work identically to native inputs, since `Input` is a
  real `<input>` under the hood.

If anything fails, investigate before changing the test — these are exactly the tests that make this
screen's race-condition fixes trustworthy.

- [ ] **Step 4: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/radio-group.tsx frontend/src/steps/ScopeEstimateStep.tsx \
  frontend/package.json frontend/package-lock.json
git commit -m "Restyle ScopeEstimateStep: shadcn Button/Input/RadioGroup, PaginatedList warnings"
```

---

## Self-Review Notes

- **Spec coverage**: implements the spec's "Component mapping" and "Warnings/problem lists" decisions
  for these 2 screens, with the documented native-`<select>`/native-checkbox deviations (both
  controller-made calls serving the spec's actual intent, explained in the Architecture section
  above — not silent departures).
- **Type consistency checked**: neither screen's exported props change. `PaginatedList` is consumed
  with the exact prop names Phase 6b-1 defined.
- **No placeholders**: every step has complete, literal code.
- **Caught in self-review**: `MappingStep.test.tsx` and `ScopeEstimateStep.test.tsx` were read in full
  before writing this plan, specifically to catch interaction-API risk (`selectOptions`/`toHaveValue`
  vs `click`) before committing to a component-swap strategy — this is what drove the native-`<select>`
  deviation, not an afterthought.
