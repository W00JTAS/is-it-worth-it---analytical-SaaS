# Impeccable Audit — IS_IT_WORTH_IT frontend — 2026-08-26

Scope: all 5 wizard screens (Upload, Mapping, Scope/scan config, Progress, Report) plus the
`AppShell` sidebar shell, in light and dark mode, at desktop (1280px) and mobile (390px) widths,
including empty/error states where the component supports one. Method: read every screen's source
and test file, ran the repo's own `contrast.mjs` and the bundled `impeccable` detector, then
temporarily patched `frontend/src/App.tsx` into a query-param-driven harness (mocked `fetch` +
`EventSource`) to render and screenshot every step/variant against the real dev server via
Playwright. The harness patch was reverted before finishing; `git status`/`git diff` on `frontend/`
show zero net change from this audit.

## Audit Health Score

| Dimension | Score | Key finding | 
|---|---|---|
| Accessibility | 1 / 4 | Focus-visible ring fails WCAG non-text contrast (1.4.11) in light mode on every button/input/select; one text pair fails 4.5:1 outright; zero `prefers-reduced-motion` handling |
| Performance | 3 / 4 | No real hotspots found; minor: no code-splitting across the 5 steps, `transition-all` on the global button variant |
| Theming | 2 / 4 | One raw, unstyled `<input type="checkbox">` bypasses the entire token/component system; scan-progress bar color never reflects a failed scan even though the text next to it does |
| Responsive Design | 1 / 4 | Every screen overflows horizontally at mobile widths — root-caused to `AppShell`'s `ScrollArea` wrapper, not any individual step |
| Implementation Integrity | 2 / 4 | `contrast.mjs` clean (0/9), bundled detector clean (0 findings) but scope-mismatched for this app (see verdict below); manual verification found 2 real drift issues tooling missed |
| **Total** | **9 / 20** | **Poor** |

Rating bands: 18–20 Excellent · 14–17 Good · 10–13 Acceptable · 6–9 Poor · 0–5 Critical.

## Implementation Integrity Verdict

**Partial pass.** The token/component system itself is coherent: one `index.css` variable set drives
every screen, every screen was independently re-verified in both themes and renders correctly
against those tokens (no broken dark mode anywhere), and the previously-shipped 6b-4 contrast fixes
hold — `node .claude/agent-memory/repo-reviewer/contrast.mjs` still reports 0/9 pairs below the AA
floor. That is real evidence of a system, not an ad-hoc pile of classNames.

Two things pull this down from a clean pass:

1. **One raw HTML control bypasses the system entirely.** `ScopeEstimateStep.tsx:230-236` renders a
   bare `<input type="checkbox" className="accent-primary" />` — no shadcn `Checkbox` primitive, no
   `--radius`/`--border`/`--ring` token participation at all beyond the check-color tint. Measured
   live: 13×13 CSS px, `appearance: auto` (full native OS chrome), sitting directly under a
   `RadioGroupItem` (Radix, 16×16, bordered, square-radius) in the same panel. This is exactly the
   "shared component vs. reinvented chrome" pattern the repo's own memory already flags for
   `ReportStep`'s hand-rolled pagination (`frontend-shadcn-swap.md`) — same bug class, new instance.
2. **The bundled `impeccable` detector's ruleset does not match this application.** `node
   .claude/skills/impeccable/scripts/detect.mjs --json frontend/src` returned `[]`. This is **not a
   false positive** — it is a scope mismatch worth naming explicitly per the audit rubric: the
   registry (`detector/registry/antipatterns.mjs`) is built for marketing/landing-page AI-slop
   (`gradient-text`, `marquee`, `hero-eyebrow-chip`, `ai-color-palette`, `theater-slop-phrase`, …)
   and for a project-supplied `.impeccable/design.json` (`design-system-color`, `design-system-radius`,
   …), neither of which exists or applies to an internal B2B data wizard with zero marketing copy. Its
   clean run carries close to zero signal here. The substantive integrity work for this app is
   `contrast.mjs` (numeric, token-aware) plus the manual code+browser pass done in this audit — which
   is precisely what surfaced both items above, neither of which any automated check in this repo
   catches (confirmed: `npm test`/`build`/`lint` all pass with both issues live).

## Executive Summary

**Score: 9/20 (Poor).** Issue counts: **1 P0, 2 P1, 3 P2, 3 P3.**

Top findings:

1. **[P0] Every screen overflows horizontally on mobile viewports** — not a per-screen bug but a
   single shared-shell defect (`AppShell.tsx:94`'s `ScrollArea`) that clips table columns, filter
   chips, and pagination text on all 5 steps the moment content's natural width exceeds ~455px.
2. **[P1] Keyboard focus indicator fails WCAG non-text contrast in light mode** on every button,
   input and select in the app — 1.4.11 requires 3:1, the effective ring renders at ~1.54:1.
3. **[P1] `ProgressStep`'s "scan succeeded" message fails WCAG AA text contrast** (4.15:1 vs. the
   4.5:1 floor) — a pair the repo's own `contrast.mjs` never enumerated, so it passed every existing
   check while live.
4. **[P2] A native, unstyled checkbox** breaks design-system consistency in `ScopeEstimateStep`.
5. **[P2] The scan-progress bar never turns red on a failed scan**, although the status text beside
   it correctly does.

Recommended next steps, in order: fix the `ScrollArea` overflow first (highest blast radius, one
component), then the two contrast failures (cheap, numeric, already have the exact ratios), then the
checkbox/progress-bar consistency items, finishing with a `polish` pass once the fixes land.

## Detailed Findings by Severity

### P0

**[P0] Horizontal overflow on every screen at mobile widths**
- **Location:** `frontend/src/AppShell.tsx:94` (`<ScrollArea className="flex-1 min-h-0">{children}</ScrollArea>`, wraps every step), root cause in `frontend/src/components/ui/scroll-area.tsx:17-22` (Radix `ScrollAreaPrimitive.Viewport`).
- **Category:** Responsive Design / Implementation Integrity.
- **Impact:** Verified live at 390×844 (iPhone-class viewport) on both `ReportStep` and `MappingStep`. Measured via `getComputedStyle`: Radix's Viewport renders an internal wrapper `<div>` with `display: table; min-width: 100%`. A `display:table` box sizes to the **max-content width of its widest child computed as if `flex-wrap` were disabled** (a documented CSS intrinsic-sizing rule for flex containers) — so the exclusion-chip row (`flex flex-wrap gap-2`, 4 chips) and the cost-config rows both contribute their "all on one line" width to the table's size. Confirmed: table wrapper rendered at **455px** while `window.innerWidth` was **390px**. Result, seen in both screenshots: table columns ("Cena hur[towa]"), chip text ("2 innej wa[luty]"), and the pagination line ("Str… / Nas[tępna]") are clipped at the right edge, with a horizontal scrollbar as the only (undiscoverable) escape hatch. Since `AppShell` wraps every one of the 5 steps, **this is not a per-screen bug** — it reproduces identically on Upload, Mapping, Scope, Progress and Report.
- **WCAG/standard:** WCAG 1.4.10 Reflow (content should not require 2-dimensional scrolling at 320–1280px widths for vertically-scrolling content) — this is a direct violation.
- **Recommendation:** Add the standard shadcn fix for this known Radix footgun — force the Viewport's inner wrapper to `display:block` (e.g. `className="... [&>div]:!block"` on `ScrollAreaPrimitive.Viewport`, or wrap children in a `w-full min-w-0` block div) so it participates in normal block sizing instead of table auto-sizing. One-line fix, whole-app blast radius.
- **Suggested command:** `harden`

### P1

**[P1] Focus-visible ring fails WCAG 1.4.11 non-text contrast in light mode, app-wide**
- **Location:** `frontend/src/components/ui/button.tsx:8` (`focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50`), same pattern in `input.tsx:11` and `selectClass.ts:6`. Token source: `frontend/src/index.css:34` (`--ring: #a1a1a1` in `:root`).
- **Category:** Accessibility.
- **Impact:** Computed with the repo's own contrast formula (`contrast.mjs`'s `ratio()`): the solid `border-ring` alone is **2.58:1** against `--background: #ffffff` (fails the 3:1 floor). The `ring-ring/50` glow, after alpha-blending 50% `#a1a1a1` over white (`#d0d0d0`), is **1.54:1** — also fails. Both components of the same focus indicator fail independently in light mode; dark mode is fine (`border-ring` alone hits 4.40:1, `#737373` on `#0a0a0a`). Every keyboard-only user tabbing through any of the 5 forms in light mode gets a focus indicator with materially insufficient contrast against the page background.
- **WCAG/standard:** WCAG 1.4.11 Non-text Contrast (AA) / 2.4.11 Focus Appearance — both require ≥3:1 for the focus indicator against adjacent colors.
- **Recommendation:** Darken `--ring` for light mode specifically (dark mode already passes), or switch the focus treatment to a token that clears 3:1 solid (e.g. reuse `--foreground` or a dedicated `--ring-light` at higher chroma/darkness), and drop the 50%-opacity glow as the sole visual cue, since alpha-blended color tokens need re-verifying against contrast independently of their full-opacity value.
- **Suggested command:** `harden`

**[P1] `ProgressStep`'s success message fails WCAG AA text contrast**
- **Location:** `frontend/src/steps/ProgressStep.tsx:48-53` (`text-sm font-medium ${scan.status === 'failed' ? 'text-destructive' : 'text-success'}`). Token: `frontend/src/index.css:36` (`--success: #0d8f4f`).
- **Category:** Accessibility / Theming (contrast-detector coverage gap).
- **Impact:** This text renders at 14px / weight 500 (`text-sm font-medium`) — not "large text" by WCAG's definition (needs ≥24px, or ≥19px **bold**), so it must clear 4.5:1. Computed with the exact luminance/ratio formula from `.claude/agent-memory/repo-reviewer/contrast.mjs`: `text-success` (`#0d8f4f`) on `--background` (`#ffffff`) = **4.15:1** — fails. The sibling failed-state color, `text-destructive` on the same background, passes at 4.77:1 (and is already the one pair `contrast.mjs` happens to enumerate, coincidentally from `ReportStep`'s usage). `contrast.mjs`'s `pairs` array never added a `text-success on bg-background, normal-size` entry for this specific usage site, so it passed 0/9 while this real failure sat unlisted — exactly the class of gap the repo's own memory (`frontend-tailwind-tokens.md`) warns "contrast is invisible to every check this repo runs."
- **WCAG/standard:** WCAG 1.4.3 Contrast (Minimum), AA, normal text floor 4.5:1.
- **Recommendation:** Darken `--success` slightly for light mode (same treatment already applied to `--warning`/`--muted-foreground` in the 6b-4 fix), and add this exact pair (`text-success` / `bg-background`, non-large) to `contrast.mjs`'s `pairs` array so the fix is guarded going forward.
- **Suggested command:** `harden`

### P2

**[P2] Native unstyled checkbox breaks design-system consistency**
- **Location:** `frontend/src/steps/ScopeEstimateStep.tsx:230-236`.
```tsx
<input
  type="checkbox"
  checked={forceRefreshStale}
  onChange={(e) => setForceRefreshStale(e.target.checked)}
  disabled={fieldsDisabled}
  className="accent-primary"
/>
```
- **Category:** Theming / Implementation Integrity.
- **Impact:** Every other interactive control in the app (`Button`, `Input`, `RadioGroupItem`, the `SELECT_CLASS` selects) is a token-driven component participating in `--radius`/`--border`/`--ring`. This one is not: measured live, it renders at 13×13 CSS px with `appearance: auto` (full native browser chrome — OS-drawn shape and border, not the app's flat `--radius: 0` aesthetic), and `accent-primary` only tints the checked-state fill color, doing nothing for border, focus ring, or corner radius. It sits directly beneath a `RadioGroupItem` in the same panel (`ScopeEstimateStep.tsx:136-144`), so the visual mismatch between a Radix-styled control and a raw native one is on-screen simultaneously. (Its clickable area is still reasonable in practice since it's wrapped in a `<label>` that includes the surrounding text, so this is a consistency finding, not a touch-target one.)
- **Recommendation:** Replace with the shadcn `Checkbox` primitive (same family as `RadioGroupItem`), or add one if not yet generated via `npx shadcn add checkbox`.
- **Suggested command:** `harden`

**[P2] Scan-progress bar color never reflects a failed scan**
- **Location:** `frontend/src/components/ui/progress.tsx:22` (`className="size-full flex-1 bg-primary transition-all"`, no variant prop) vs. `frontend/src/steps/ProgressStep.tsx:48-53` (status text correctly switches to `text-destructive` on failure).
- **Category:** Theming.
- **Impact:** Verified via the `progress-failed-light.png` capture: at `status: 'failed'`, the bar is still the same neutral grey as a healthy in-progress scan, while the text underneath turns red. A user glancing at just the bar (the more prominent, larger element) gets no visual signal that anything went wrong; only the smaller text line beneath carries the color cue. This is the same "the token/color layer stopped one component short" pattern already logged for the ReportStep link fix in project memory, new instance.
- **Recommendation:** Parametrize `Progress`'s indicator color (e.g. accept a `variant`/`indicatorClassName` prop) and pass `text-destructive`'s color through when `scan.status === 'failed'`.
- **Suggested command:** `colorize`

**[P2] Report screen's filter row still wraps to two rows at desktop width (confirmed still live)**
- **Location:** `frontend/src/steps/ReportStep.tsx:443-481` (three `<select className={SELECT_CLASS}>` in one `flex flex-wrap gap-3` row, no width override), `frontend/src/components/ui/selectClass.ts`.
- **Category:** Responsive Design / Implementation Integrity.
- **Impact:** Already documented in `.claude/agent-memory/repo-reviewer/frontend-shadcn-swap.md` as an expected consequence of `SELECT_CLASS`'s fixed width with no per-call-site override — confirmed still present via live screenshot (`report-light-full.png`) at 1280px: Kategoria+Status share a line, Sortowanie wraps to its own line below. Not a new discovery, but unresolved as of this audit and worth carrying forward rather than assuming a later phase fixed it.
- **Recommendation:** Apply the same `cn(SELECT_CLASS, 'w-auto')`-at-call-site pattern the memory file already prescribes, or move to a `flex-1 min-w-[8rem]` sizing so three selects share the row proportionally.
- **Suggested command:** `layout`

### P3

**[P3] No `prefers-reduced-motion` handling anywhere**
- **Location:** grep-verified zero matches for `prefers-reduced-motion`/`reducedMotion` in `frontend/src/`. Animated surfaces: `components/ui/sheet.tsx:38,63` (slide/fade in/out), `components/ui/sidebar.tsx:220,232,291,404` (width/position transitions), `components/ui/skeleton.tsx:7` (`animate-pulse`).
- **Category:** Accessibility.
- **Impact:** None of these are large or vestibular-triggering individually, but the app has zero fallback for users who've set the OS-level reduce-motion preference — a rubric-listed accessibility check with a clean, mechanical failure signature.
- **Recommendation:** Add a `@media (prefers-reduced-motion: reduce)` block in `index.css` that neutralizes `animate-*`/`transition-*`/`duration-*` utilities globally (Tailwind's `motion-reduce:` variant, or a blanket override), matching the pattern the deleted `design-motion-principles` skill's own accessibility reference presumably prescribed.
- **Suggested command:** `harden`

**[P3] Icon-only theme toggle has no tooltip, unlike every nav icon beside it**
- **Location:** `frontend/src/AppShell.tsx:82-89` (`<Button variant="ghost" size="icon" aria-label={...}>`) vs. `frontend/src/components/ui/sidebar.tsx:517-536` (`SidebarMenuButton`'s `tooltip` prop, used for every step icon).
- **Category:** Accessibility / Implementation Integrity (consistency).
- **Impact:** Every wizard-step icon in the collapsed sidebar gets a hover/focus tooltip (`tooltip={step.label}`) as a sighted-user discovery aid; the theme toggle sitting in the same rail has only an `aria-label` (screen-reader only) and no visible tooltip, so a sighted mouse user has no way to learn what the moon/sun icon does without clicking it.
- **Recommendation:** Wrap the theme-toggle `Button` in the same `Tooltip`/`TooltipTrigger`/`TooltipContent` pattern `SidebarMenuButton` already uses.
- **Suggested command:** `polish`

**[P3] No code-splitting across the 5 wizard steps**
- **Location:** `frontend/src/App.tsx:1-9` — all 5 step components statically imported; grep-verified zero `React.lazy`/dynamic `import()` calls anywhere in `frontend/src/`.
- **Category:** Performance.
- **Impact:** Every step's code (including `ReportStep`, the largest at 524 lines, with its own table/pagination/product-drill-down logic) ships in the initial bundle even though only one step renders at a time in a strictly sequential wizard — a natural, low-risk `React.lazy` boundary per step. Not measured against an actual built bundle size, so this is a structural observation rather than a proven regression.
- **Recommendation:** Wrap each step import in `React.lazy` + `Suspense` in `App.tsx`.
- **Suggested command:** `optimize`

## Patterns & Systemic Issues

- **The contrast detector's `pairs` array is hand-maintained and grows one fix at a time, not one
  audit at a time.** Both 6b-4's own fixes and this audit's new finding (`text-success` on
  `bg-background` at normal size) show the same shape: a real usage site introduced in a step file,
  never mirrored into `contrast.mjs`'s enumerated list, so it silently passed. The script is correct
  and cheap to extend — it just needs a discipline of "new colored text on a token background → add
  the pair" rather than "add the pair once it's already reported wrong."
- **Component-family drift keeps happening at the same rate memory predicts.** `frontend-shadcn-swap.md`
  already names two instances (native `<table>` swap side effects, `ReportStep`'s hand-rolled
  pagination vs. `MappingStep`'s `Pagination` primitive). This audit found a third and fourth
  (native checkbox, non-parametrized `Progress` color) in the same shape: one component quietly opts
  out of the shared system while its siblings stay on it. Worth a lint rule or a repo-reviewer
  detector (`grep -rn '<input type="checkbox"' frontend/src/steps/`) rather than catching it by hand
  each phase.
- **Every layout defect found (the mobile overflow, the still-open filter-row wrap) traces to a
  shared/reused primitive, not to step-specific markup.** The step components themselves are
  well-structured; the primitives one layer down (`ScrollArea`, `SELECT_CLASS`) are where the actual
  bugs live. Future review passes should weight primitive-level scrutiny higher than step-level
  scrutiny.

## Positive Findings

- **Dark mode is genuinely solid.** All 5 screens, plus 3 error states and 2 empty states, were
  screenshotted in both themes; every single one renders correctly with no unstyled flashes, no
  invisible text, no broken component in dark mode. This is a real, hard-won result given the recent
  full re-skin.
- **`contrast.mjs` reports 0/9 sub-AA pairs** — the specific issues it was built to guard (the
  6b-4-era `text-primary`/`text-warning`/`text-muted-foreground` failures) all stayed fixed.
- **Conditional empty-state hiding works correctly everywhere it was tested.** `MappingStep` hides
  its warnings list and sample-rows table cleanly when both are empty (verified via the `variant=empty`
  capture); `ReportStep` correctly shows "Brak danych do policzenia" only when genuinely idle/empty,
  never simultaneously with a real error (this exact "empty vs. error must never coexist" invariant
  has its own regression test in `ReportStep.test.tsx:109-118`).
- **Icon-only sidebar nav buttons keep a valid accessible name even when visually collapsed.** The
  `<span>{step.label}</span>` inside `SidebarMenuButton` is clipped via `overflow-hidden`, not
  `display:none`/`visibility:hidden`, so it stays in the accessibility tree and the button's computed
  name is never empty — screen readers get the step name even before the hover tooltip appears. This
  is easy to get wrong and wasn't.
- **The in-flight request-ordering guard pattern is applied consistently.** Confirmed present and
  correctly wired in all three steps that fetch from user actions (`MappingStep`, `ScopeEstimateStep`,
  `ReportStep` ×2) — the exact pattern project memory flags as easy to omit.
- **Disabled step-navigation in the sidebar works correctly at every breakpoint tested**, including
  the mobile `Sheet` variant — future steps render visibly greyed and carry a real `disabled`
  attribute (not just visual styling), confirmed via the `mapping-mobile-sidebar-open` capture.

## Recommended Actions, in priority order

1. **Fix the `AppShell`/`ScrollArea` horizontal-overflow bug** (`harden`) — single component, every
   screen affected, WCAG 1.4.10 violation.
2. **Darken `--ring` for light mode** so the focus indicator clears 3:1 (`harden`).
3. **Darken `--success` for light mode and add the missing pair to `contrast.mjs`** (`harden`).
4. **Replace the raw checkbox in `ScopeEstimateStep` with the shadcn `Checkbox` primitive** (`harden`).
5. **Parametrize `Progress`'s indicator color for the failed state** (`colorize`).
6. **Fix the still-open `ReportStep` filter-row wrap** (`layout`).
7. Add a global `prefers-reduced-motion` fallback (`harden`); tooltip the theme toggle (`polish`);
   consider `React.lazy` per wizard step (`optimize`).
8. **`polish`** — once 1–6 land, a pass to catch any residual spacing/alignment fallout from the
   `ScrollArea` and checkbox fixes.
