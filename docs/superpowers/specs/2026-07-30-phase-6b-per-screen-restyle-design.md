# Phase 6b — Per-screen restyle + shell/UX fixes — design spec

Status: **approved** (2026-07-30, via interactive brainstorming, following live use of the shipped
Phase 6a shell).

## Context

Phase 6a (`2026-07-30-phase-6a-visual-foundation-shell.md`) shipped the design-token foundation and
the `AppShell` sidebar shell, deliberately scoped to *not* touch any step screen's markup. The user
then ran the app for real (their actual ~115k-row supplier catalog) and reported concrete problems,
confirmed by running the same flow headlessly (screenshots not committed):

- All 5 step screens (`UploadStep`, `MappingStep`, `ScopeEstimateStep`, `ProgressStep`, `ReportStep`)
  still use their pre-Phase-6a hardcoded `slate-950`/`slate-900`/`slate-800`/`emerald-600`
  Tailwind classes, chosen when the app was dark-only. Sitting inside the new light-default shell,
  this produces near-invisible light-gray-on-white text (headings, labels) and jarring dark
  navy/black boxes for every native `<input>`/`<select>` — a "mid-migration" look, exactly as
  flagged as a risk in Phase 6a's own final review.
- The sidebar's "smooth auto-hide" (the user's original ask, back in Phase 6a's brainstorm) was
  actually implemented as a manual click-to-collapse toggle — there is no hover-driven behavior at
  all. Confirmed live: moving the mouse away from an expanded sidebar does not collapse it.
- `MappingStep`'s CSV-parse warnings and `ScopeEstimateStep`'s scan warnings both render an
  unbounded `<ul>`/`<li>` list — with a real catalog, this is hundreds of lines long and dominates
  the page.
- The browser's default scrollbar looks out of place against the new design system.

This phase fixes all of the above. It does **not** change any screen's information architecture,
validation, or API surface — same scope discipline as Phase 6a ("re-skin plus a new shell, not a
UX/flow redesign"), except where explicitly noted (the warnings-list pagination is a genuine new UI
pattern, not present before).

## Decisions

| Topic | Decision |
|---|---|
| Scope | All 5 step screens restyled onto the Phase 6a token system (not just Upload/Scope, which the user named explicitly — Mapping/Progress/Report have the identical defect, confirmed by `grep` for `slate-*` classes across all 5 files). |
| Sidebar behavior | Changes from "always expanded, manual collapse" to **hover-driven**: `AppShell` sets `defaultOpen={false}` and drives the sidebar's existing `open` state via `onMouseEnter`/`onMouseLeave` on the sidebar's wrapper element. Expands smoothly on hover (reusing the transition already built into shadcn's `Sidebar`), collapses back to icon-only when the mouse leaves. The existing manual trigger (mobile) and rail-click (desktop) still work as an explicit pin/unpin action layered on top — hovering is the primary interaction, clicking remains available. |
| Warnings/problem lists | New shared `PaginatedList` component (10 items/page, per user's explicit choice), built on shadcn's `pagination` primitive. Replaces both `MappingStep`'s CSV-preview-warnings `<ul>` and `ScopeEstimateStep`'s scan-warnings `<ul>` — one component, two call sites, not two separate implementations of the same pattern. |
| Scrollbar | shadcn's `scroll-area` component (Radix `ScrollArea`) wraps `AppShell`'s main content area, replacing the browser-default scrollbar site-wide with a thin, theme-colored thumb (`bg-border`, already themed correctly out of the box — no new color needed). |
| Component mapping | Native `<input type="file">` → shadcn `Input` (styled trigger, still a real file input under the hood — no custom file-picker chrome, that's out of scope). Native `<input type="number">` → shadcn `Input type="number"`. Native `<select>` (Mapping's 5 column dropdowns) → shadcn `Select`. Native radio buttons (Scope's "Pełny skan" / "Próbka per kategoria") → shadcn `RadioGroup`. All hardcoded `slate-*`/`emerald-*` color classes → semantic tokens (`bg-card`, `text-foreground`, `text-muted-foreground`, `border-border`, `text-success`/`text-warning`/`text-destructive` for signal colors) — this is the actual fix for the contrast bugs, not a coat of paint on top of them. |
| Report screen | Keeps its Phase-5b information architecture (verdict → cost-config card → exclusion chips → scenario matrix → category table → paginated product drill-down) exactly as-is — only the color/token layer changes, per Phase 6a spec's own carry-over note. Its *existing* product-drill-down pagination (backend-driven, `/report/products?page=`) is unrelated to the new `PaginatedList` (that one's for small, already-fully-loaded client-side lists like CSV warnings — no reason to route warnings through a backend pagination round-trip). |
| Skills used | `frontend-design` was invoked for calibration but the brief's visual direction is already fully pinned down by the approved Phase 6 spec — no new aesthetic decisions here, this phase is disciplined *application* of the existing system plus the two genuine UX fixes (hover sidebar, pagination). `impeccable`'s audit/critique workflow is used for the final whole-branch review, per the original Phase 6 spec's testing section. |

## `PaginatedList` component

New shared component, `frontend/src/components/PaginatedList.tsx` (app-level component, not a
shadcn primitive — composes `Pagination`/`PaginationContent`/`PaginationItem`/`PaginationPrevious`/
`PaginationNext` from `@/components/ui/pagination`).

```ts
interface PaginatedListProps<T> {
  items: readonly T[]
  pageSize: number         // always 10, passed explicitly rather than hardcoded inside, so a caller
                            // could override later without touching the component
  renderItem: (item: T, index: number) => React.ReactNode
  emptyState?: React.ReactNode
}
```

Purely client-side pagination over an already-in-memory array (both call sites already have the
full warnings array in hand — `CsvPreview.warnings` and `EstimateResult.warnings` are both small,
bounded lists even at catalog scale, unlike the Report's product drill-down). Renders the current
page's slice via `renderItem`, plus a `Pagination` control below when `items.length > pageSize`
(hidden entirely when everything fits on one page — no empty pager for a 3-item list). Page state is
local (`useState`), reset to page 1 whenever `items` changes (a new CSV preview or a new estimate
replaces the whole warnings list, so page position from the old list is meaningless).

## Sidebar hover behavior

`AppShell.tsx` changes:
- `SidebarProvider` gains `defaultOpen={false}` (starts collapsed) and becomes a **controlled**
  component: `open`/`onOpenChange` are lifted into `AppShell`'s own `useState`, so hover handlers can
  drive it directly rather than fighting the provider's internal state.
- The hover region is the `Sidebar` element itself (which already spans the full collapsed-icon-rail
  width even when collapsed) — `onMouseEnter` sets `open=true`, `onMouseLeave` sets `open=false`.
  No debounce/delay in this phase (YAGNI — add one later only if real use reveals flicker).
- The existing `SidebarTrigger` (mobile header) and `SidebarRail` (desktop click-to-toggle) keep
  working unchanged — they call the same lifted `setOpen`, so a click still works as an explicit
  toggle independent of hover.
- Tooltips on collapsed menu items (already implemented in Phase 6a) become *more* relevant now that
  collapsed is the resting state, not just an option — no code change needed there, just confirms the
  existing `tooltip={step.label}` prop was the right call.

## Testing

- `PaginatedList`: unit tests for page slicing, page-count/hidden-pager-on-one-page, and reset-on-
  `items`-change behavior — a small, pure, easily-tested component in isolation.
- `AppShell`: existing tests updated for the new controlled-`open` pattern; new tests for
  mouse-enter-expands / mouse-leave-collapses, and that a manual trigger/rail click still works
  alongside hover.
- Each restyled screen: existing test suites updated only where they queried something that no
  longer exists (e.g. a raw `<select>` becomes a shadcn `Select`, which changes how RTL needs to
  interact with it — `userEvent.click` on the trigger, then `userEvent.click` on the item, replacing
  a plain `selectOptions` call). No test *coverage* is dropped — same assertions, adapted queries.
- `npm run build` remains a required last step, per the standing project rule.
- Final whole-branch review explicitly re-invokes `impeccable`'s audit/critique against the finished
  result in both light and dark mode, since that's exactly the class of defect (contrast, mode-
  specific breakage) this phase exists to fix.

## Out of scope for this phase

- Any change to screen information architecture, validation rules, or API surface.
- The Report's product-drill-down pagination (already exists, backend-driven, untouched).
- A debounce/delay on the hover-sidebar interaction (add only if it proves necessary).
- Custom styling of the native file-picker button itself (OS-level chrome, `Input` just wraps it
  consistently with other inputs — no cross-browser custom file-picker UI).
- Phase 6's original next step (`ShopifySource` sketch) — still queued after the visual redesign
  finishes.
