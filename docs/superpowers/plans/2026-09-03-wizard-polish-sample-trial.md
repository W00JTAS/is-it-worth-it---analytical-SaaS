# Wizard Polish + Sample-Trial Entry Point Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing 5-step wizard for a normal widescreen desktop (not the narrow/tall
layout it inherited), fix the AppShell title, MappingStep and ScopeEstimateStep's concrete UX
problems, and add a zero-setup "try it on a sample" entry point using 3 real 25-product samples
pulled from the repo's own catalog data.

**Architecture:** Every change is a targeted edit to an existing component (`AppShell`,
`UploadStep`, `MappingStep`, `ScopeEstimateStep`, `PaginatedList`, `App`) plus 3 new static CSV
assets under `frontend/public/samples/`. No backend change, no new API endpoint, no new dependency
beyond one shadcn component (`collapsible`). The sample-trial path reuses `POST /scans` exactly as
today — `MappingStep` is skipped client-side by passing a hardcoded `ColumnMapping` straight to
`App`'s existing state, the backend never knows the difference between an uploaded file and a
bundled one.

**Tech Stack:** React + TypeScript, Vite, Tailwind v4 (CSS variables in `index.css`), shadcn/ui
(Radix primitives), Vitest + Testing Library + `@testing-library/user-event`.

**Spec:** `docs/superpowers/specs/2026-09-03-wizard-polish-sample-trial-design.md`

## Global Constraints

- Target viewport for layout decisions: a normal widescreen desktop monitor (reference 2560×1440),
  not a narrow/tall one. Containers may grow past today's `max-w-md`/`max-w-3xl`, never full-bleed.
- `MappingStep` keeps its native `<select>` elements — do not swap to shadcn's `Select` (breaks
  `userEvent.selectOptions()`-based tests, see `.claude/rules/frontend-ui.md`).
- Every new `data-*:` Tailwind variant must use the bracketed value form
  (`group-data-[collapsible=icon]:...`), never a bare presence form
  (`group-data-collapsible-icon:...`) — the latter silently no-ops against Radix's
  attribute-value pairs. See `.claude/rules/frontend-ui.md`.
- `npm run build` (`tsc -b`) is mandatory before any task is considered done, not just `npm test`.
- No backend change of any kind in this plan.
- No new runtime dependency beyond `npx shadcn add collapsible` (Task 7).

---

### Task 1: `AppShell` — "IS?" title reveal

**Files:**
- Modify: `frontend/src/AppShell.tsx:58-60`
- Test: `frontend/src/AppShell.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new (purely internal markup change, `AppShellProps` unchanged).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/AppShell.test.tsx`, inside the existing `describe('AppShell', ...)` block:

```tsx
  it('shows a compact "IS?" mark, with the full title as one text node when expanded', () => {
    render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    // RTL's default getByText matching (`getNodeText`) only reads an
    // element's DIRECT text-node children, not full recursive textContent —
    // confirmed live in this worktree by dumping matcher calls, see the SDD
    // ledger. So neither `getByText('IS').closest('span')` (returns the leaf
    // "IS" span itself) nor a custom matcher keyed on `content === '...'`
    // (the outer wrapper's direct-children content is `""`, since its
    // children are all <span> elements, not text nodes) can find the outer
    // wrapper via getByText. Instead: find the uniquely-matching leaf "IS"
    // text node, walk up exactly one level to its actual parent, then check
    // that parent's real DOM `.textContent` (not RTL's getNodeText).
    const inner = screen.getByText('IS')
    const header = inner.parentElement
    expect(header?.tagName.toLowerCase()).toBe('span')
    expect(header!.textContent).toBe('IS IT WORTH IT?')
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- AppShell.test.tsx`
Expected: FAIL — `screen.getByText('IS')` finds nothing, since today's header renders the single
string `"IS IT WORTH IT"` with no separate `"IS"` node.

- [ ] **Step 3: Replace the title markup**

In `frontend/src/AppShell.tsx`, replace line 59:

```tsx
            <span className="px-2 py-1 text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">IS IT WORTH IT</span>
```

with:

```tsx
            <span className="flex items-baseline overflow-hidden px-2 py-1 text-sm font-semibold tracking-tight">
              <span>IS</span>
              <span className="grid grid-cols-[1fr] transition-[grid-template-columns] duration-200 ease-linear group-data-[collapsible=icon]:grid-cols-[0fr]">
                <span className="min-w-0 overflow-hidden whitespace-nowrap">{' IT WORTH IT'}</span>
              </span>
              <span>?</span>
            </span>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- AppShell.test.tsx`
Expected: PASS — all `AppShell` tests, including the new one.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/AppShell.tsx src/AppShell.test.tsx
git commit -m "feat(appshell): collapse sidebar title to 'IS?' instead of hiding it"
```

---

### Task 2: `index.css` — native `<select>` dark-mode fix

**Files:**
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing (pure CSS, no component API change).

No unit test is possible here — jsdom does not render real native `<select>` popups, so this is
verified manually in a real browser (see Step 3). This is the one step in this plan without a
TDD red/green cycle, by necessity, not by choice.

- [ ] **Step 1: Add `color-scheme` to both themes**

In `frontend/src/index.css`, inside the `:root { ... }` block (after `--radius: 0rem;`), add:

```css
  color-scheme: light;
```

Inside the `.dark { ... }` block (as its first line), add:

```css
  color-scheme: dark;
```

- [ ] **Step 2: Run the build**

Run: `cd frontend && npm run build`
Expected: succeeds (this is a CSS-only change, build should be unaffected).

- [ ] **Step 3: Manual verification**

Start the dev server (`cd frontend && npm run dev`), open the app, toggle to dark mode, navigate to
`MappingStep` (upload any small CSV to reach it), open one of the 5 native `<select>` dropdowns.
Confirm the option list is now rendered with dark background / light text, matching the app's theme
— not the previous near-invisible light-on-light popup. Confirm light mode is unaffected (still a
light popup, unchanged from before).

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/index.css
git commit -m "fix(theme): set color-scheme so native selects render in the app's dark theme"
```

---

### Task 3: `UploadStep` — remove redundant filename, widen container

**Files:**
- Modify: `frontend/src/steps/UploadStep.tsx`
- Test: `frontend/src/steps/UploadStep.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `UploadStepProps` unchanged (`onFileSelected` only — the sample-trial props are added
  in Task 9, not here).

- [ ] **Step 1: Delete the now-obsolete test**

In `frontend/src/steps/UploadStep.test.tsx`, delete the whole `it('shows the chosen file name', ...)`
block (lines 31-39) — the behavior it asserts is being removed in Step 3 below. The other two tests
in the file are untouched.

- [ ] **Step 2: Run tests to confirm the remaining two still pass**

Run: `cd frontend && npm test -- UploadStep.test.tsx`
Expected: PASS (2 tests) — confirms nothing else in the file depended on the deleted test's setup.

- [ ] **Step 3: Edit the component**

In `frontend/src/steps/UploadStep.tsx`, remove line 25:

```tsx
      {file && <p className="text-sm text-muted-foreground">{file.name}</p>}
```

and change the outer container's className on line 19 from:

```tsx
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
```

to:

```tsx
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-8">
```

- [ ] **Step 4: Run tests and build**

Run: `cd frontend && npm test -- UploadStep.test.tsx && npm run build`
Expected: PASS / succeeds.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/steps/UploadStep.tsx src/steps/UploadStep.test.tsx
git commit -m "fix(upload): drop redundant filename display, widen container"
```

---

### Task 4: `MappingStep` — auto-refresh preview on field change

**Files:**
- Modify: `frontend/src/steps/MappingStep.tsx`
- Test: `frontend/src/steps/MappingStep.test.tsx`

**Interfaces:**
- Consumes: nothing new (`loadPreview`, `previewRequestIdRef` already exist in this file).
- Produces: `handleFieldChange` now triggers a debounced re-fetch; the manual `handleRefresh`
  function and its "Odśwież podgląd" `Button` are removed. No prop/type change — `MappingStepProps`
  is unaffected, so Task 5 and Task 9 are unaffected by this task's internals.

- [ ] **Step 1: Rewrite the two tests that click "Odśwież podgląd"**

In `frontend/src/steps/MappingStep.test.tsx`, replace the test at lines 64-77
(`'re-fetches the preview with the edited mapping when Odśwież podgląd is clicked'`) with:

```tsx
  it('auto-refreshes the preview after a debounced delay when a mapping field changes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ delay: null })
    const spy = vi.spyOn(client, 'getCsvPreview').mockResolvedValue(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)
    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')

    await user.selectOptions(screen.getByLabelText('EAN'), 'Kategoria')
    await vi.advanceTimersByTimeAsync(400)

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith(FILE, {
        name: 'Nazwa', wholesale_price: 'Cena hurtowa', ean: 'Kategoria', category: 'Kategoria', sku: 'SKU',
      }),
    )
    vi.useRealTimers()
  })
```

Replace the test at lines 110-131 (`'disables all mapping selects and Dalej while a refresh request
is in flight'`) with:

```tsx
  it('disables all mapping selects and Dalej while a refresh request is in flight', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ delay: null })
    let resolveRefresh: (value: CsvPreview) => void = () => {}
    const spy = vi.spyOn(client, 'getCsvPreview')
    spy.mockResolvedValueOnce(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)
    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')

    spy.mockImplementationOnce(
      () => new Promise<CsvPreview>((resolve) => { resolveRefresh = resolve }),
    )
    await user.selectOptions(screen.getByLabelText('EAN'), 'Kategoria')
    await vi.advanceTimersByTimeAsync(400)

    expect(screen.getByLabelText('Nazwa')).toBeDisabled()
    expect(screen.getByLabelText('Cena hurtowa')).toBeDisabled()
    expect(screen.getByLabelText('EAN')).toBeDisabled()
    expect(screen.getByLabelText('Kategoria')).toBeDisabled()
    expect(screen.getByLabelText('SKU (opcjonalne)')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Dalej' })).toBeDisabled()

    resolveRefresh(PREVIEW)
    await waitFor(() => expect(screen.getByLabelText('Nazwa')).toBeEnabled())
    vi.useRealTimers()
  })
```

Replace the test at lines 136-158 (`'does not let a refresh response overwrite the mapping the user
chose locally'`) with:

```tsx
  it('does not let a refresh response overwrite the mapping the user chose locally', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const user = userEvent.setup({ delay: null })
    let resolveRefresh: (value: CsvPreview) => void = () => {}
    const spy = vi.spyOn(client, 'getCsvPreview')
    spy.mockResolvedValueOnce(PREVIEW)
    render(<MappingStep file={FILE} onConfirmed={vi.fn()} />)
    await screen.findByText('1 / 1 wierszy sparsowanych poprawnie')

    // User clears SKU back to "-- brak --", which now triggers a debounced
    // refresh on its own (no button to click anymore).
    await user.selectOptions(screen.getByLabelText('SKU (opcjonalne)'), '')
    spy.mockImplementationOnce(
      () => new Promise<CsvPreview>((resolve) => { resolveRefresh = resolve }),
    )
    await vi.advanceTimersByTimeAsync(400)

    // Backend echoes the auto-detected SKU back, as `_merge_mapping`'s `or`
    // fallback would for a field sent as null.
    resolveRefresh(PREVIEW)
    await waitFor(() => expect(screen.getByLabelText('Nazwa')).toBeEnabled())

    expect(screen.getByLabelText('SKU (opcjonalne)')).toHaveValue('')
    vi.useRealTimers()
  })
```

- [ ] **Step 2: Run tests to verify these three fail**

Run: `cd frontend && npm test -- MappingStep.test.tsx`
Expected: FAIL for these 3 tests — the "Odśwież podgląd" button still exists and no debounce fires
yet, so `getByRole('button', { name: 'Odśwież podgląd' })` calls that no longer appear in the test
file aren't the issue; rather, no auto-refresh happens on a plain `selectOptions` today, so
`getCsvPreview` is never called a second time and the assertions time out.

- [ ] **Step 3: Implement the debounced auto-refresh**

In `frontend/src/steps/MappingStep.tsx`, add a ref near the top of the component (next to
`previewRequestIdRef`):

```tsx
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
```

Replace `handleFieldChange` and delete `handleRefresh` entirely:

```tsx
  function handleFieldChange(field: keyof ColumnMapping, value: string) {
    const next = { ...mapping, [field]: value || null }
    setMapping(next)
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => loadPreview(next), 400)
  }
```

Add a cleanup effect right after the existing mount effect (so the pending timer doesn't fire after
unmount):

```tsx
  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
  }, [])
```

Remove the `Button`/`handleRefresh` JSX block:

```tsx
            <Button type="button" onClick={handleRefresh} disabled={isLoading} className="self-start">
              Odśwież podgląd
            </Button>
```

(this whole block, previously right after the closing `</div>` of the fields section, is deleted —
nothing replaces it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- MappingStep.test.tsx`
Expected: PASS — all tests in the file, including the 3 rewritten ones.

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/steps/MappingStep.tsx src/steps/MappingStep.test.tsx
git commit -m "feat(mapping): auto-refresh preview on field change instead of a manual button"
```

---

### Task 5: `MappingStep` — two-column wide layout

**Files:**
- Modify: `frontend/src/steps/MappingStep.tsx`
- Test: `frontend/src/steps/MappingStep.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new (pure layout/className change — no new props, no behavior change, so no
  new test assertions are needed beyond confirming existing tests still pass against the new DOM
  shape).

- [ ] **Step 1: Confirm the baseline**

Run: `cd frontend && npm test -- MappingStep.test.tsx`
Expected: PASS (this task changes layout only, not queries — `getByLabelText`/`getByText` don't
depend on DOM nesting, so no test should need rewriting; this step just confirms the starting point
is green before a layout-only change).

- [ ] **Step 2: Restructure the JSX into two columns**

In `frontend/src/steps/MappingStep.tsx`, change the outer container (line 95) from:

```tsx
    <div className="mx-auto flex max-w-3xl flex-col gap-12 p-8">
```

to:

```tsx
    <div className="mx-auto flex max-w-6xl flex-col gap-6 p-8">
```

Wrap the existing three `<section>` elements (fields, parsed-count/warnings, sample-rows table) plus
the final `<Button>` into a two-column grid. Change:

```tsx
      {preview && (
        <>
          <section className="flex flex-col gap-4">
```

to:

```tsx
      {preview && (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[24rem_1fr]">
          <div className="flex flex-col gap-6">
            <section className="flex flex-col gap-4">
```

Move the parsed-count/warnings `<section>` (today's second `<section>`) to close inside that same
left `<div>`. Concretely, after the existing fields `<section>` closes, keep the "Odśwież podgląd"
button removed in Task 4, then close the fields section, then the warnings section stays adjacent,
then close the left column `<div>` and open the right column before the sample-rows `<section>`:

```tsx
          </section>

          <section className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>
              {preview.parsed_count} / {preview.total_rows} wierszy sparsowanych poprawnie
            </p>
            {preview.warnings.length > 0 && (
              <>
                <PaginatedList
                  items={preview.warnings}
                  pageSize={10}
                  renderItem={(warning) => <span className="text-warning">{warning}</span>}
                />
                {preview.warning_count > preview.warnings.length && (
                  <p className="text-sm text-warning">
                    ...i {preview.warning_count - preview.warnings.length} więcej
                  </p>
                )}
              </>
            )}
          </section>

          <Button
            type="button"
            onClick={() => onConfirmed(mapping)}
            disabled={!requiredFilled || isLoading}
            className="self-start"
          >
            Dalej
          </Button>
          </div>

          {preview.sample_rows.length > 0 && (
            <section className="flex min-w-0 flex-col gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Przykładowe wiersze</h2>
              <Table>
```

(the `Table`/`TableHeader`/`TableBody` block itself is unchanged — only its enclosing `<section>`
moves from being the 3rd stacked block to the right column, and the `Dalej` `Button` moves from
being the very last stacked element to the bottom of the left column, since it acts on the mapping
form, not the table). Close the outer grid `<div>` where the old fragment `</>` used to close:

```tsx
            </section>
          )}
        </div>
      )}
```

- [ ] **Step 3: Run tests and build**

Run: `cd frontend && npm test -- MappingStep.test.tsx && npm run build`
Expected: PASS / succeeds — no query in the test file depends on section order or nesting depth.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add src/steps/MappingStep.tsx
git commit -m "feat(mapping): two-column layout so the wide viewport doesn't need side/page scroll"
```

---

### Task 6: `PaginatedList` — `columns` prop, wired into `MappingStep`'s warnings

**Files:**
- Modify: `frontend/src/components/PaginatedList.tsx`
- Modify: `frontend/src/steps/MappingStep.tsx`
- Test: `frontend/src/components/PaginatedList.test.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: `PaginatedListProps<T>` gains `columns?: number` (default `1`). Existing callers
  (`ScopeEstimateStep`'s warnings list) are source-compatible with no change.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/PaginatedList.test.tsx` (inside the existing `describe` block —
read the file first to match its existing `render`/import style before inserting):

```tsx
  it('renders items in 2 grid columns, column-major, when columns={2}', () => {
    const items = Array.from({ length: 10 }, (_, i) => `item-${i}`)
    render(
      <PaginatedList
        items={items}
        pageSize={10}
        columns={2}
        renderItem={(item) => <span>{item}</span>}
      />
    )

    const listItems = screen.getAllByRole('listitem')
    expect(listItems).toHaveLength(10)
    // Column-major fill: item-0..item-4 are the first column, item-5..item-9 the second —
    // NOT row-major (item-0, item-1 side by side).
    expect(listItems[0]).toHaveTextContent('item-0')
    expect(listItems[4]).toHaveTextContent('item-4')
    expect(listItems[5]).toHaveTextContent('item-5')
  })
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- PaginatedList.test.tsx`
Expected: FAIL — `columns` isn't a recognized prop yet (TypeScript) and the grid layout doesn't
exist (though the assertions themselves would still technically pass against the flat list unless
the `columns` prop causes a type error — treat a `tsc` failure here as the expected red state too).

- [ ] **Step 3: Add the `columns` prop**

In `frontend/src/components/PaginatedList.tsx`, change the props interface:

```tsx
interface PaginatedListProps<T> {
  items: readonly T[]
  pageSize: number
  renderItem: (item: T, index: number) => ReactNode
  emptyState?: ReactNode
  columns?: number
}
```

Change the function signature and the `<ul>` rendering:

```tsx
export function PaginatedList<T>({ items, pageSize, renderItem, emptyState, columns = 1 }: PaginatedListProps<T>) {
```

```tsx
  const rows = columns > 1 ? Math.ceil(pageItems.length / columns) : undefined

  return (
    <div className="space-y-3">
      <ul
        className={columns > 1 ? 'grid grid-flow-col gap-x-6 gap-y-1' : 'space-y-1'}
        style={rows ? { gridTemplateRows: `repeat(${rows}, minmax(0, auto))` } : undefined}
      >
        {pageItems.map((item, index) => (
          <li key={start + index}>{renderItem(item, start + index)}</li>
        ))}
      </ul>
```

(only the `<ul ...>` opening tag changes — everything inside `.map(...)` and the `Pagination` block
below stay exactly as they are today).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- PaginatedList.test.tsx`
Expected: PASS — all tests in the file, including the new one.

- [ ] **Step 5: Wire `columns={2}` into `MappingStep`'s warnings list**

In `frontend/src/steps/MappingStep.tsx`, change the `PaginatedList` call inside the warnings
`<section>` (moved there in Task 5) from:

```tsx
                <PaginatedList
                  items={preview.warnings}
                  pageSize={10}
                  renderItem={(warning) => <span className="text-warning">{warning}</span>}
                />
```

to:

```tsx
                <PaginatedList
                  items={preview.warnings}
                  pageSize={10}
                  columns={2}
                  renderItem={(warning) => <span className="text-warning">{warning}</span>}
                />
```

`ScopeEstimateStep.tsx`'s own `PaginatedList` call (for scan warnings) is **not** touched — it keeps
the default `columns={1}`.

- [ ] **Step 6: Run full frontend test suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS / succeeds.

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/components/PaginatedList.tsx src/components/PaginatedList.test.tsx src/steps/MappingStep.tsx
git commit -m "feat(paginated-list): support a 2-column layout, use it for mapping warnings"
```

---

### Task 7: `ScopeEstimateStep` — advanced-settings disclosure + wider layout

**Files:**
- Modify: `frontend/src/steps/ScopeEstimateStep.tsx`
- Test: `frontend/src/steps/ScopeEstimateStep.test.tsx`
- Create (via `npx shadcn add collapsible`): `frontend/src/components/ui/collapsible.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new (`ScopeEstimateStepProps` unchanged) — `maxConcurrency` and
  `stalenessThresholdDays` state and their change handlers are untouched, only their JSX moves
  inside a disclosure.

- [ ] **Step 1: Add the shadcn `collapsible` component**

Run: `cd frontend && npx shadcn add collapsible`

Then run the repo's mandatory bare-`data-*` check (per `.claude/rules/frontend-ui.md`) even though
the `PostToolUse` hook should already have run it:

Run: `grep -rnoE '[a-z-]*data-[a-z0-9-]+(/[a-zA-Z0-9_-]+)?:' frontend/src/components/ui/collapsible.tsx | grep -v 'data-\['`
Expected: no output (no bare `data-*:` variant in the generated file). If this prints anything,
stop and fix it before continuing — do not proceed with a known-broken generated component.

- [ ] **Step 2: Write the failing tests**

Replace the test at lines 127-155 in `frontend/src/steps/ScopeEstimateStep.test.tsx`
(`'disables all scope fields while an estimate request is in flight, closing the field-change
race'`) — insert opening the disclosure before querying the now-hidden fields:

```tsx
  it('disables all scope fields while an estimate request is in flight, closing the field-change race', async () => {
    let resolveCreateScan!: (value: typeof CREATE_RESULT) => void
    const createScanSpy = vi.spyOn(client, 'createScan').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreateScan = resolve
        }),
    )
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)
    await userEvent.click(screen.getByRole('button', { name: /ustawienia zaawansowane/i }))

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))

    expect(screen.getByLabelText('Pełny skan')).toBeDisabled()
    expect(screen.getByLabelText('Próbka per kategoria')).toBeDisabled()
    expect(screen.getByLabelText(/limit czasu dostawy/i)).toBeDisabled()
    expect(screen.getByLabelText(/limit współbieżności/i)).toBeDisabled()
    expect(screen.getByLabelText(/próg nieświeżości/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Oszacuj koszt' })).toBeDisabled()

    resolveCreateScan(CREATE_RESULT)

    expect(await screen.findByText(/bez odświeżania/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Pełny skan')).not.toBeDisabled()
  })
```

Add one new test, right after it, asserting the disclosure's default-collapsed / plain-language
behavior:

```tsx
  it('keeps advanced settings collapsed by default, with plain-language help text once opened', async () => {
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    expect(screen.queryByLabelText(/limit współbieżności/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/próg nieświeżości/i)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /ustawienia zaawansowane/i }))

    expect(screen.getByLabelText(/limit współbieżności/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/limit współbieżności/i)).toHaveValue(5)
    expect(screen.getByLabelText(/próg nieświeżości/i)).toHaveValue(14)
  })
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npm test -- ScopeEstimateStep.test.tsx`
Expected: FAIL — there is no "Ustawienia zaawansowane" button yet, so
`getByRole('button', { name: /ustawienia zaawansowane/i })` throws.

- [ ] **Step 4: Implement the disclosure**

In `frontend/src/steps/ScopeEstimateStep.tsx`, add the import:

```tsx
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ChevronDown } from 'lucide-react'
```

Change the outer container (line 128) from:

```tsx
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
```

to:

```tsx
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-8">
```

Replace the two standalone concurrency/staleness `<div>` blocks (today's lines 175-199) with:

```tsx
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" className="group flex items-center gap-2 self-start px-0 text-sm text-muted-foreground">
            <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            Ustawienia zaawansowane
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-4 pt-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="max-concurrency">Limit współbieżności</Label>
            <p className="text-xs text-muted-foreground">
              Ile ofert sprawdzamy jednocześnie. Wyższa wartość = szybciej, ale większe ryzyko
              trafienia w limity dostawcy danych.
            </p>
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
            <p className="text-xs text-muted-foreground">
              Po ilu dniach cena z poprzedniego skanu jest uznawana za nieaktualną i sprawdzana
              ponownie zamiast użyta z pamięci.
            </p>
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
        </CollapsibleContent>
      </Collapsible>
```

Note: `Button`'s `variant="ghost"` matches this file's existing import of `Button` from
`@/components/ui/button` — no new import needed for that. The `group`/`group-data-[state=open]:`
pair on the chevron follows the bracketed-variant rule from Global Constraints — Radix's
`Collapsible.Trigger` sets `data-state="open"|"closed"`, an attribute-**value** pair, so the bare
form would silently no-op here exactly as described in `.claude/rules/frontend-ui.md`.

Widen the result box: change (today's line 210):

```tsx
        <div className="flex flex-col gap-3 rounded-md border border-border p-4 text-sm text-foreground">
```

to:

```tsx
        <div className="flex flex-col gap-3 rounded-md border border-border p-6 text-sm text-foreground">
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm test -- ScopeEstimateStep.test.tsx`
Expected: PASS — all tests in the file.

- [ ] **Step 6: Run full suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS / succeeds.

- [ ] **Step 7: Commit**

```bash
cd frontend && git add src/steps/ScopeEstimateStep.tsx src/steps/ScopeEstimateStep.test.tsx src/components/ui/collapsible.tsx
git commit -m "feat(scope): hide concurrency/staleness behind advanced settings, widen result box"
```

---

### Task 8: Generate the 3 sample CSVs

**Files:**
- Create: `frontend/public/samples/kuchnia.csv`
- Create: `frontend/public/samples/zabawki.csv`
- Create: `frontend/public/samples/elektronika.csv`

**Interfaces:**
- Consumes: `supplier_z_cenami_i_ean.csv` at the repo root (read-only).
- Produces: 3 static CSV files, each with header `SKU;ean;nazwa;kategoria;cena` and exactly 25 data
  rows, semicolon-delimited, quoted fields — the exact shape `Task 9`'s hardcoded `ColumnMapping`
  and `Task 10`'s file-construction code depend on.

This task has no test cycle (it produces static data, not code) — verification is a row/column
count check, not TDD.

- [ ] **Step 1: Write and run the generation script**

Save this as a temporary file (do not commit it — it's a one-off, not reusable tooling) at
`/tmp/generate_samples.py`, run from the repo root:

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
    print(name, 'candidates:', len(rows))
    sample = random.Random(42).sample(rows, 25)
    with open(f'frontend/public/samples/{name}.csv', 'w', newline='', encoding='utf-8') as out:
        w = csv.DictWriter(out, fieldnames=FIELDNAMES, delimiter=';', quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(sample)
    print(f'wrote frontend/public/samples/{name}.csv')
```

Run: `mkdir -p frontend/public/samples && python3 /tmp/generate_samples.py`
Expected output: 3 lines of `<name> candidates: <n>` (n in the thousands for each bucket) followed
by 3 `wrote frontend/public/samples/<name>.csv` lines.

- [ ] **Step 2: Verify the output**

Run: `for f in frontend/public/samples/*.csv; do echo "$f: $(($(wc -l < "$f") - 1)) rows"; done`
Expected: all 3 files report exactly `25 rows`.

Run: `head -3 frontend/public/samples/elektronika.csv`
Expected: a header line `"SKU";"ean";"nazwa";"kategoria";"cena"` followed by 2 real product rows
with non-empty EAN, name, category and a positive price.

- [ ] **Step 3: Commit**

```bash
git add frontend/public/samples/kuchnia.csv frontend/public/samples/zabawki.csv frontend/public/samples/elektronika.csv
git commit -m "feat(samples): add 3 curated 25-product sample CSVs for the trial flow"
```

---

### Task 9: `UploadStep` — sample-trial category cards

**Files:**
- Modify: `frontend/src/steps/UploadStep.tsx`
- Test: `frontend/src/steps/UploadStep.test.tsx`

**Interfaces:**
- Consumes: the 3 static files from Task 8, fetched at runtime via `fetch('/samples/<id>.csv')`
  (Vite serves `frontend/public/*` at the site root — no import needed).
- Produces: `UploadStepProps` gains `onSampleSelected: (file: File, columnMapping: ColumnMapping) =>
  void`, required — `App.tsx` (Task 10) is the only caller and must supply it.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/steps/UploadStep.test.tsx`:

```tsx
describe('UploadStep sample-trial cards', () => {
  const originalFetch = global.fetch

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('fetches the bundled CSV and calls onSampleSelected with a File and the fixed mapping', async () => {
    const csvBody = '"SKU";"ean";"nazwa";"kategoria";"cena"\n"A1";"5901234123457";"Czajnik";"AGD";"99.00"\n'
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob([csvBody], { type: 'text/csv' })),
    }) as unknown as typeof fetch
    const onSampleSelected = vi.fn()
    render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={onSampleSelected} />)

    await userEvent.click(screen.getByRole('button', { name: /kuchnia/i }))

    await waitFor(() => expect(onSampleSelected).toHaveBeenCalledTimes(1))
    expect(global.fetch).toHaveBeenCalledWith('/samples/kuchnia.csv')
    const [file, mapping] = onSampleSelected.mock.calls[0]
    expect(file).toBeInstanceOf(File)
    expect(file.name).toBe('kuchnia.csv')
    expect(mapping).toEqual({
      name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: 'SKU',
    })
  })

  it('renders all three category cards', () => {
    render(<UploadStep onFileSelected={vi.fn()} onSampleSelected={vi.fn()} />)

    expect(screen.getByRole('button', { name: /kuchnia/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /zabawki/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /elektronika/i })).toBeInTheDocument()
  })
})
```

Update the `import` line at the top of the file to include `waitFor` and `afterEach`:

```tsx
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- UploadStep.test.tsx`
Expected: FAIL — `onSampleSelected` isn't an accepted prop yet (TypeScript) and no category cards
exist.

- [ ] **Step 3: Implement the sample-trial section**

In `frontend/src/steps/UploadStep.tsx`, replace the whole file:

```tsx
import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { Cpu, ToyBrick, UtensilsCrossed, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ColumnMapping } from '../api/types'

interface UploadStepProps {
  onFileSelected: (file: File) => void
  onSampleSelected: (file: File, columnMapping: ColumnMapping) => void
}

const SAMPLE_COLUMN_MAPPING: ColumnMapping = {
  name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: 'SKU',
}

interface SampleCategory {
  id: string
  label: string
  description: string
  icon: LucideIcon
}

const SAMPLE_CATEGORIES: readonly SampleCategory[] = [
  { id: 'kuchnia', label: 'Kuchnia i AGD', description: '25 realnych produktów AGD', icon: UtensilsCrossed },
  { id: 'zabawki', label: 'Zabawki', description: '25 realnych zabawek', icon: ToyBrick },
  { id: 'elektronika', label: 'Elektronika', description: '25 realnych produktów elektronicznych', icon: Cpu },
]

export function UploadStep({ onFileSelected, onSampleSelected }: UploadStepProps) {
  const [file, setFile] = useState<File | null>(null)
  const [loadingSampleId, setLoadingSampleId] = useState<string | null>(null)
  const [sampleError, setSampleError] = useState<string | null>(null)

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  async function handleSampleClick(category: SampleCategory) {
    setSampleError(null)
    setLoadingSampleId(category.id)
    try {
      const response = await fetch(`/samples/${category.id}.csv`)
      if (!response.ok) throw new Error(`sample fetch failed: ${response.status}`)
      const blob = await response.blob()
      const sampleFile = new File([blob], `${category.id}.csv`, { type: 'text/csv' })
      onSampleSelected(sampleFile, SAMPLE_COLUMN_MAPPING)
    } catch {
      setSampleError('Nie udało się wczytać przykładowej próbki')
    } finally {
      setLoadingSampleId(null)
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 p-8">
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold text-foreground">Wgraj katalog</h1>
        <div className="flex flex-col gap-2">
          <Label htmlFor="csv-upload">Plik CSV od hurtowni</Label>
          <Input id="csv-upload" type="file" accept=".csv" onChange={handleChange} />
        </div>
        <Button type="button" disabled={!file} onClick={() => file && onFileSelected(file)}>
          Dalej
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Nie masz jeszcze własnego pliku? Wypróbuj na przykładowej próbce:
        </p>
        {sampleError && <p className="text-sm text-destructive">{sampleError}</p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {SAMPLE_CATEGORIES.map((category) => (
            <Button
              key={category.id}
              type="button"
              variant="outline"
              disabled={loadingSampleId !== null}
              onClick={() => handleSampleClick(category)}
              className="flex h-auto flex-col items-start gap-2 border-border p-4 text-left whitespace-normal"
            >
              <category.icon className="size-5 text-muted-foreground" />
              <span className="font-medium text-foreground">{category.label}</span>
              <span className="text-xs font-normal text-muted-foreground">
                {loadingSampleId === category.id ? 'Wczytywanie…' : category.description}
              </span>
            </Button>
          ))}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- UploadStep.test.tsx`
Expected: PASS — all tests, including the new `describe('UploadStep sample-trial cards', ...)`
block.

- [ ] **Step 5: Run full suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS / succeeds — `App.tsx` will fail to typecheck at this point since it doesn't yet pass
`onSampleSelected` (fixed in Task 10). If `tsc -b` fails **only** on `App.tsx`'s missing prop, that
is the expected, temporary state until Task 10 lands — confirm no *other* file fails.

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/steps/UploadStep.tsx src/steps/UploadStep.test.tsx
git commit -m "feat(upload): add sample-trial category cards (kitchen/toys/electronics)"
```

---

### Task 10: `App` — wire the sample-trial flow, skipping `MappingStep`

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `UploadStep`'s `onSampleSelected` prop (Task 9).
- Produces: nothing new externally — this is the final wiring task, no other task depends on it.

- [ ] **Step 1: Write the failing test**

Read `frontend/src/App.test.tsx` first to match its existing mocking/rendering conventions (it
likely mocks `MappingStep`/`ScopeEstimateStep` or drives the real lazy-loaded components — follow
whatever pattern is already there). Add a test asserting that clicking a sample card advances
straight to the `scope` step, skipping `mapping`:

```tsx
  it('skips MappingStep and lands on ScopeEstimateStep when a sample category is chosen', async () => {
    const csvBody = '"SKU";"ean";"nazwa";"kategoria";"cena"\n"A1";"5901234123457";"Czajnik";"AGD";"99.00"\n'
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob([csvBody], { type: 'text/csv' })),
    }) as unknown as typeof fetch

    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /kuchnia/i }))

    expect(await screen.findByText('Zakres skanu')).toBeInTheDocument()
    expect(screen.queryByText('Mapowanie kolumn')).not.toBeInTheDocument()
  })
```

(adapt the exact `render`/import lines to match whatever `App.test.tsx` already imports — this test
body assumes `userEvent`, `screen`, `render` are already imported the way `UploadStep.test.tsx`
imports them; if `App.test.tsx` mocks the lazy step components instead of rendering them for real,
follow that existing pattern rather than this literal body).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- App.test.tsx`
Expected: FAIL — `App` doesn't pass `onSampleSelected` to `UploadStep` yet, so `tsc` fails, or (once
that specific prop is stubbed) the click has no effect and the test times out waiting for "Zakres
skanu".

- [ ] **Step 3: Wire the handler**

In `frontend/src/App.tsx`, change the `<UploadStep ... />` usage from:

```tsx
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('mapping')
          }}
        />
      )}
```

to:

```tsx
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('mapping')
          }}
          onSampleSelected={(selected, mapping) => {
            setFile(selected)
            setColumnMapping(mapping)
            setStep('scope')
          }}
        />
      )}
```

No other change to `App.tsx` is needed — `columnMapping` and `setStep` already exist and are already
of the right types (`ColumnMapping | null` and the `WizardStep` setter).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- App.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run full suite and build**

Run: `cd frontend && npm test && npm run build`
Expected: PASS / succeeds — this is the task where the `tsc -b` failure noted in Task 9 Step 5
disappears.

- [ ] **Step 6: Commit**

```bash
cd frontend && git add src/App.tsx src/App.test.tsx
git commit -m "feat(app): wire sample-trial cards to skip mapping and land on scope config"
```

---

## Final verification (after all 10 tasks)

- [ ] Run `cd frontend && npm test && npm run build` one more time from a clean state — full suite,
  full build.
- [ ] Manually run the app end to end in a real browser, in both light and dark mode: (a) upload a
  real CSV through the normal path, confirm `MappingStep`'s two-column layout and auto-refresh, and
  the dark-mode select fix from Task 2; (b) from a fresh load, click each of the 3 sample cards in
  turn and confirm each lands directly on `ScopeEstimateStep` with "Zakres skanu" showing, and that
  "Ustawienia zaawansowane" is collapsed by default; (c) hover the sidebar collapsed/expanded and
  confirm the "IS?" ⇄ "IS IT WORTH IT?" reveal animates smoothly.
- [ ] Per this repo's standing rule (`IS_IT_WORTH_IT/CLAUDE.md`), run the `repo-reviewer` subagent
  for a whole-branch review before merging — this plan's own task-level reviews check conformance
  to *this plan*, not independently against the codebase, which is exactly the gap that rule exists
  to close.
