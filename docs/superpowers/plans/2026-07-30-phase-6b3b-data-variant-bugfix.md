# Phase 6b-3b — Fix bare data-variant bugs in scroll-area/separator/sheet — Implementation Plan

**Goal:** Fix a real, confirmed rendering bug shipped in Phase 6a and still live on `master`: three
shadcn-generated components (`scroll-area.tsx`, `separator.tsx`, `sheet.tsx`) use bare Tailwind
`data-*:` variants (which compile to attribute-*presence* selectors) that don't match the actual
`data-orientation`/`data-state` attribute-*value* pairs Radix sets — so the styling gated by those
variants has never activated. Most consequential: the site-wide custom scrollbar's track has no
explicit width/height at all, meaning it has likely been rendering invisibly or malformed since
Phase 6a shipped. This is the same bug class already found and fixed twice this project
(`sidebar.tsx`'s `data-active:` in Phase 6a's final review, `radio-group.tsx`'s `data-checked:` in
Phase 6b-3's final review) — this plan closes out the remaining known instances.

**Architecture:** Pure CSS-variant-syntax fix in 3 already-owned shadcn component files. No behavior,
props, or logic change anywhere — purely correcting Tailwind selector syntax to match what Radix
actually sets.

**Tech Stack:** Tailwind v4, Radix UI (via shadcn), Vitest.

## Global Constraints

- Zero behavior/prop/logic changes — this is a pure visual-bug fix.
- `npm run build` required alongside `npm test`.
- No new tests are strictly required (jsdom doesn't apply real CSS, so this bug class is invisible to
  the existing test suite either way — this was true for the two prior fixes of the same bug class
  too) — but a scoped visual sanity check (documented in Step 3) is required, not just a code diff.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/ui/scroll-area.tsx` | Fix: `data-horizontal:`/`data-vertical:` → `data-[orientation=horizontal]:`/`data-[orientation=vertical]:` |
| `frontend/src/components/ui/separator.tsx` | Fix: `data-horizontal:`/`data-vertical:` → `data-[orientation=horizontal]:`/`data-[orientation=vertical]:` |
| `frontend/src/components/ui/sheet.tsx` | Fix: `data-open:`/`data-closed:` → `data-[state=open]:`/`data-[state=closed]:` |

---

### Task 1: Fix the three components

**Files:**
- Modify: `frontend/src/components/ui/scroll-area.tsx`
- Modify: `frontend/src/components/ui/separator.tsx`
- Modify: `frontend/src/components/ui/sheet.tsx`

**Interfaces:**
- Consumes: nothing new.
- Produces: no change to any exported component's props or API — same `ScrollArea`, `Separator`,
  `Sheet`/`SheetContent`/etc. exports, same call sites throughout the app, unchanged.

- [ ] **Step 1: Fix `scroll-area.tsx`**

In `frontend/src/components/ui/scroll-area.tsx`, the `ScrollBar` component's className currently
reads (confirmed via direct read of the current file):

```
"flex touch-none p-px transition-colors select-none data-horizontal:h-2.5 data-horizontal:flex-col data-horizontal:border-t data-horizontal:border-t-transparent data-vertical:h-full data-vertical:w-2.5 data-vertical:border-l data-vertical:border-l-transparent"
```

Replace every `data-horizontal:` with `data-[orientation=horizontal]:` and every `data-vertical:`
with `data-[orientation=vertical]:` (4 occurrences each, 8 total). Result:

```
"flex touch-none p-px transition-colors select-none data-[orientation=horizontal]:h-2.5 data-[orientation=horizontal]:flex-col data-[orientation=horizontal]:border-t data-[orientation=horizontal]:border-t-transparent data-[orientation=vertical]:h-full data-[orientation=vertical]:w-2.5 data-[orientation=vertical]:border-l data-[orientation=vertical]:border-l-transparent"
```

Do not change anything else in this file — `data-orientation={orientation}` (already correct, this is
what Radix's own scrollbar primitive also sets, confirmed) and every other line stay as-is.

- [ ] **Step 2: Fix `separator.tsx`**

In `frontend/src/components/ui/separator.tsx`, the `Separator` component's className currently reads:

```
"shrink-0 bg-border data-horizontal:h-px data-horizontal:w-full data-vertical:w-px data-vertical:self-stretch"
```

Replace `data-horizontal:` → `data-[orientation=horizontal]:` and `data-vertical:` →
`data-[orientation=vertical]:` (2 occurrences each, 4 total). Result:

```
"shrink-0 bg-border data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:w-px data-[orientation=vertical]:self-stretch"
```

- [ ] **Step 3: Fix `sheet.tsx`**

In `frontend/src/components/ui/sheet.tsx`, two className strings use bare `data-open:`/`data-closed:`
variants (confirmed via direct read — the overlay's className and the content panel's className both
contain these). Read the current file first to get the exact strings (they're long, with several
other `data-[side=...]:` segments already correctly bracketed — only the `data-open:`/`data-closed:`
parts are wrong), then replace every `data-open:` with `data-[state=open]:` and every `data-closed:`
with `data-[state=closed]:`, leaving every other class (including the already-correct
`data-[side=...]:` variants and any `data-[side=...]:data-open:...` compound ones, which become
`data-[side=...]:data-[state=open]:...`) untouched.

Do a final `grep -n 'data-open:\|data-closed:'` over the file after editing to confirm zero bare
occurrences remain.

- [ ] **Step 4: Verify with a real browser render**

This bug class is invisible to `npm test` (jsdom doesn't apply real CSS) and to `npm run build`
(it's valid Tailwind syntax either way, just semantically wrong) — the only way to actually confirm
the fix is to look at rendered output. Start the dev server (`npm run dev`) and either:
- use whatever browser-automation tool is available in this environment to screenshot a page with a
  visible scroll area (any wizard step, since `AppShell` wraps all of them in `ScrollArea`) before and
  after the fix, confirming a visible scrollbar track/thumb appears when content overflows, or
- if no browser automation is available, inspect the compiled CSS output directly: `grep
  'data-\[orientation' dist/assets/*.css` after `npm run build`, confirming the bracketed selectors
  are present in the built stylesheet (proving Tailwind actually generated rules for them, which it
  would not have for the old bare `data-horizontal`/`data-vertical` form only if those genuinely never
  matched real content — cross-check by also confirming the OLD bare-form selectors are cleaner-room
  absent or present-but-inert; the bracketed form being present and correctly scoped is the meaningful
  signal).

Record what you did and what you saw in the report — this step is required, not optional, given the
bug was invisible to every automated check that already ran on it twice before (Phase 6a's and
6b-3's own test/build/lint all passed while these bugs were live).

- [ ] **Step 5: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/scroll-area.tsx frontend/src/components/ui/separator.tsx \
  frontend/src/components/ui/sheet.tsx
git commit -m "Fix bare data-*: variants in scroll-area/separator/sheet (never matched Radix's actual attributes)"
```

---

## Self-Review Notes

- **Spec coverage**: this is a bugfix plan, not a spec-driven feature plan — it exists because the
  Phase 6b-3 final review found this class of bug in 3 files outside that plan's own diff scope and
  explicitly recommended a dedicated fix rather than waiting for it to be rediscovered piecemeal.
- **No placeholders**: exact before/after strings given for `scroll-area.tsx` and `separator.tsx`;
  `sheet.tsx` is given as a precise instruction (find-and-replace by pattern, confirmed via grep) since
  its full class string is long and reproducing it by hand in this plan risks a transcription error
  that a direct find-and-replace against the real file avoids.
- **Known risk explicitly addressed**: this bug class passed `npm test`/`npm run build`/`npm run
  lint` twice already while broken — Step 4 exists specifically because "the tests passed" would
  otherwise be treated as sufficient verification, and it demonstrably is not for this bug class.
