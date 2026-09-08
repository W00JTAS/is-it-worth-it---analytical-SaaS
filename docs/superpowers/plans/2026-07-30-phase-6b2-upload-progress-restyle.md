# Phase 6b-2 — Upload + Progress screen restyle — Implementation Plan

**Goal:** Restyle `UploadStep` and `ProgressStep` — the two smallest, simplest screens — onto the
Phase 6a/6b-1 token system and shadcn components, fixing the near-invisible light-mode text and
unstyled native inputs/buttons the user reported.

**Architecture:** Pure re-skin: replace hardcoded `slate-*`/`emerald-*` Tailwind classes with semantic
tokens (`text-foreground`, `text-muted-foreground`, `text-destructive`, `text-success`) and native
`<input>`/`<button>` elements with shadcn `Input`/`Button`/`Label`/`Progress`. No change to either
screen's logic, props, or information architecture.

**Tech Stack:** React 19, shadcn/ui (already adopted), Vitest + React Testing Library.

## Global Constraints

- Implements the relevant slice of `docs/superpowers/specs/2026-07-30-phase-6b-per-screen-restyle-design.md`
  — the "Component mapping" decision (native inputs → shadcn components, `slate-*` → semantic tokens).
- No change to either screen's logic, props, callbacks, or validation.
- `npm run build` required on every task, alongside `npm test`.
- Any existing test asserting a literal Tailwind class name that no longer exists must be updated to
  assert the new one — never weakened or deleted, per the spec's testing section.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/ui/label.tsx`, `progress.tsx` | New shadcn components |
| `frontend/src/steps/UploadStep.tsx` | Modified: shadcn `Input`/`Button`/`Label`, semantic tokens |
| `frontend/src/steps/ProgressStep.tsx` | Modified: shadcn `Progress`/`Button`, semantic tokens |
| `frontend/src/steps/ProgressStep.test.tsx` | Modified: one test's literal-classname assertion updated |

---

### Task 1: Restyle `UploadStep`

**Files:**
- Create: `frontend/src/components/ui/label.tsx` (via `npx shadcn add label`)
- Modify: `frontend/src/steps/UploadStep.tsx`

**Interfaces:**
- Consumes: `Input`, `Button` (already installed, Phase 6a), `Label` (this task).
- Produces: no change to `UploadStepProps` (`{ onFileSelected: (file: File) => void }`) — `App.tsx`
  is untouched.

- [ ] **Step 1: Install the shadcn label component**

```bash
cd frontend && npx shadcn add label
```

- [ ] **Step 2: Replace `UploadStep.tsx`'s content**

```tsx
import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface UploadStepProps {
  onFileSelected: (file: File) => void
}

export function UploadStep({ onFileSelected }: UploadStepProps) {
  const [file, setFile] = useState<File | null>(null)

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Wgraj katalog</h1>
      <div className="flex flex-col gap-2">
        <Label htmlFor="csv-upload">Plik CSV od hurtowni</Label>
        <Input id="csv-upload" type="file" accept=".csv" onChange={handleChange} />
      </div>
      {file && <p className="text-sm text-muted-foreground">{file.name}</p>}
      <Button type="button" disabled={!file} onClick={() => file && onFileSelected(file)}>
        Dalej
      </Button>
    </div>
  )
}
```

- [ ] **Step 3: Run `UploadStep`'s existing tests — no changes expected**

```bash
npm test -- UploadStep
```

Expected: PASS (3 tests, unchanged) — the tests query by `getByLabelText(/plik CSV/i)`,
`getByRole('button', { name: 'Dalej' })`, and `getByText(file.name)`, none of which depend on the
specific classes/elements being replaced. `Label`'s Radix implementation renders a real `<label
for="csv-upload">`, so `getByLabelText` keeps working; `Input`/`Button` both render real
`<input>`/`<button>` elements under the hood.

- [ ] **Step 4: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ui/label.tsx frontend/src/steps/UploadStep.tsx \
  frontend/package.json frontend/package-lock.json
git commit -m "Restyle UploadStep onto shadcn components and semantic tokens"
```

---

### Task 2: Restyle `ProgressStep`

**Files:**
- Create: `frontend/src/components/ui/progress.tsx` (via `npx shadcn add progress`)
- Modify: `frontend/src/steps/ProgressStep.tsx`
- Modify: `frontend/src/steps/ProgressStep.test.tsx`

**Interfaces:**
- Consumes: `Button` (Phase 6a), `Progress` (this task).
- Produces: no change to `ProgressStepProps` (`{ scanId: string; onDone: (scanId: string) => void }`).

- [ ] **Step 1: Install the shadcn progress component**

```bash
cd frontend && npx shadcn add progress
```

- [ ] **Step 2: Update the one test that asserts a literal Tailwind class**

In `frontend/src/steps/ProgressStep.test.tsx`, the "shows a distinct, non-success treatment when
status is failed" test currently asserts:

```ts
expect(failedMessage.className).toContain('text-red-400')
expect(failedMessage.className).not.toContain('text-emerald-400')
```

Replace those two lines with:

```ts
expect(failedMessage.className).toContain('text-destructive')
expect(failedMessage.className).not.toContain('text-success')
```

(This is the only test in the file that inspects a literal class name — the other 5 tests query by
text/role and need no changes.)

- [ ] **Step 3: Run the tests to verify the updated assertion fails against the current implementation**

```bash
npm test -- ProgressStep
```

Expected: FAIL on the updated assertion — the component still renders `text-red-400`/`text-emerald-400`
at this point, not `text-destructive`/`text-success`.

- [ ] **Step 4: Replace `ProgressStep.tsx`'s content**

```tsx
import { useScanEvents } from '../api/useScanEvents'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'

interface ProgressStepProps {
  scanId: string
  onDone: (scanId: string) => void
}

export function ProgressStep({ scanId, onDone }: ProgressStepProps) {
  const { scan, source, error } = useScanEvents(scanId)

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-muted-foreground">Łączenie ze skanem…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.round((scan.completed_products / scan.total_products) * 100)
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed'

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Przebieg skanu</h1>
      <Progress value={percent} />
      <p className="text-sm text-muted-foreground">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-muted-foreground">
          Połączenie na żywo zerwane — aktualizacja co kilka sekund.
        </p>
      )}
      {isTerminal && (
        <>
          <p
            className={`text-sm font-medium ${
              scan.status === 'failed' ? 'text-destructive' : 'text-success'
            }`}
          >
            {scan.status === 'done' ? 'Skan zakończony.' : 'Skan zakończony z błędami.'}
          </p>
          <Button type="button" onClick={() => onDone(scanId)}>
            Zobacz raport
          </Button>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm test -- ProgressStep
```

Expected: PASS (6 tests).

- [ ] **Step 6: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ui/progress.tsx frontend/src/steps/ProgressStep.tsx \
  frontend/src/steps/ProgressStep.test.tsx frontend/package.json frontend/package-lock.json
git commit -m "Restyle ProgressStep onto shadcn components and semantic tokens"
```

---

## Self-Review Notes

- **Spec coverage**: implements the spec's "Component mapping" decision for exactly these 2 screens.
  Mapping/Scope+Estimate/Report are separate, later plans (6b-3, 6b-4).
- **Type consistency checked**: neither screen's exported props change; `App.tsx` needs no changes.
- **No placeholders**: every step has complete, literal code, including the exact test-assertion diff.
- **Caught in self-review**: `ProgressStep.test.tsx`'s literal `text-red-400`/`text-emerald-400`
  class-name assertions were found by grepping the test file, not assumed — this is exactly the kind
  of test-adaptation the Phase 6b spec's testing section anticipated.
