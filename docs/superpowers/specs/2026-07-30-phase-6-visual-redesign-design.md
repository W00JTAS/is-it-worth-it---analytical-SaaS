# Phase 6 (redirect) — Visual design system — design spec

Status: **approved** (2026-07-30, via interactive brainstorming with visual companion).

## Context

Phases 0–5c (see `2026-07-28-is-it-worth-it-design.md` and the phase 3/4/5a/5b/5c specs) built the
full wizard end-to-end: `Upload → Mapping → Scope+Estimate → Progress → Report`, all backed by real
tests, all merged to `master`. The originally-planned next step was Phase 6 (`ShopifySource` sketch).
The user chose to defer that and instead do a visual design pass over the app itself, since it has
never had one: every screen so far was styled with default Tailwind utility classes as each phase
shipped, except the Report screen (Phase 5b), which got a deliberate but screen-local "Apple-style"
direction (dark `slate-950`/`emerald-600`, tabular-numeral verdict, Settings.app-style grouped cards).
There has never been a wizard-wide shell (no header, no step indicator — `App.tsx` just swaps one
full-screen step component for another) and no cross-screen visual system.

This phase produces a single, deliberate visual system — tokens, shell/navigation, and how it applies
to all 5 screens — replacing the ad hoc per-phase styling with one coherent design, built on shadcn/ui
as an editable code base rather than a hands-off dependency. Phase 6 (`ShopifySource`) returns to the
queue after this.

## Process note

This design was produced with the brainstorming skill's visual companion (browser-based mockups), not
text-only dialogue — several of the decisions below (visual direction, light/dark handling, shell
layout) were picked by the user clicking through rendered comparisons, not by describing preferences
in words. The mockups themselves are not part of this repo's history.

## Decisions

| Topic | Decision |
|---|---|
| Scope | All 5 screens (Upload, Mapping, Scope+Estimate, Progress, Report) plus a new wizard-wide shell. The already-shipped Report screen is explicitly back in scope for restyling — not pinned as a constraint. |
| Visual direction | "Financial terminal": dense data-forward layout, monospace type throughout, numeric hierarchy over decorative chrome, semantic green/amber/red signal colors. Chosen over an "Apple-style dark continuity" option and a "warm approachable SaaS" option after live comparison. |
| Color mode | **Light is the default mode**; dark is available via an explicit toggle. Not dark-only, not light-only — both, light first. Initial mode follows `prefers-color-scheme`; a manual override is persisted to `localStorage` and wins on every later load. |
| Design token base | shadcn/ui's built-in **"Mono"** tweakcn theme, adopted close to verbatim: Geist Mono as the sole font (sans and mono both mapped to it), full neutral-grayscale light+dark token maps, `0rem` radius (sharp corners). This is the only tweakcn theme that already matches the financial-terminal direction almost exactly. |
| Signal colors (added on top of Mono) | Mono ships no success color and a single destructive red; this phase adds `--success` (worth-it / positive margin) and `--warning` (marginal / exclusion / anomaly) as new CSS variables, reusing Mono's existing `--destructive` for negative/skip rather than introducing a second red. Light: success `#0d8f4f`, warning `#a3760a`. Dark: success `#39d98a`, warning `#e0b84d`. Applied **as text/icon color only** — never as a colored background box or extra border around a stat (explicit user correction during mockup review: the boxed/bordered treatment read as noisy in light mode, plain colored figures on the ambient background read cleanly in both modes). |
| Component base | shadcn/ui components, installed via the shadcn CLI as owned source (`src/components/ui/`), then edited directly for this app's needs — not used as an unmodified drop-in dependency. This satisfies the explicit requirement that the site "looks the way it's supposed to look," with shadcn as the starting scaffold, not the final word. |
| Shell / navigation | A collapsible **icon sidebar** (shadcn `sidebar` block, `collapsible="icon"` mode) listing all 5 wizard steps with icons, smooth animated collapse to an icon-only rail (built into the shadcn sidebar component), theme toggle docked at the bottom. Chosen over a compact top stepper bar after live comparison — user prioritized the more app-like persistent nav over the extra horizontal space a top bar would have preserved. |
| Icons | `lucide-react` (shadcn's default icon set) — `Upload`, `Columns3` (Mapping), `Target` (Scope+Estimate), `Activity` (Progress), `BarChart3` (Report). |
| Skills used | `frontend-design` and `impeccable` (already installed in this project) are invoked during the implementation plan's design/polish work — this spec sets direction and tokens, but per-screen detail work and a final visual QA pass explicitly go through those skills, not ad hoc Tailwind authorship. |

## Design tokens

Base: shadcn "Mono" theme, applied via CSS custom properties (Tailwind v4's `@theme inline` block in
`frontend/src/index.css`, replacing the current bare `@import "tailwindcss";`):

**Light** (default): `background #ffffff`, `foreground #0a0a0a`, `card #ffffff`, `muted #f5f5f5`,
`muted-foreground #717171`, `border #e5e5e5`, `primary #737373`, `destructive #e7000b`.

**Dark**: `background #0a0a0a`, `foreground #fafafa`, `card #191919`, `muted #262626`,
`muted-foreground #a1a1a1`, `border #383838`, `destructive #ff6467`.

**Added semantic tokens** (both modes): `--success` / `--warning` per the table above. These are the
only tokens this phase adds beyond what the Mono theme ships — everything else (spacing, radius, font)
is taken as-is.

**Font**: `Geist Mono`, self-hosted via the `@fontsource/geist-mono` npm package (no runtime CDN
dependency) — mapped to both `font-sans` and `font-mono` Tailwind theme keys, so every piece of text in
the app, not just numerals, renders in the monospace face. This is a deliberate, direction-defining
choice (confirmed across all three mockup rounds), not an oversight.

**Radius**: `0rem` (sharp corners), taken verbatim from the Mono theme — a deliberate part of the
financial-terminal character, replacing the `rounded-2xl`/`rounded-md` mix used ad hoc across the
existing screens.

**Dark mode mechanism**: a `dark` class on `<html>`, toggled via Tailwind v4's `@custom-variant dark
(&:is(.dark *));`. On first load, apply based on `window.matchMedia('(prefers-color-scheme: dark)')`;
after that, `localStorage` key `isItWorthIt.theme` (`'light' | 'dark'`) wins whenever present, written
whenever the user flips the sidebar's toggle. Same persistence pattern already used for `ReportStep`'s
cost config — no new persistence approach introduced.

## Shell

New top-level layout wrapping all 5 steps in `App.tsx`, replacing the current bare
`<div className="min-h-screen ...">` step-swap:

- shadcn `SidebarProvider` + `Sidebar` (`collapsible="icon"`) on the left, containing:
  - App name/wordmark at the top.
  - 5 nav items, one per wizard step, each with a lucide icon + label. Items reflect wizard state:
    completed steps are reachable-looking but not necessarily clickable-backward in this phase (see
    Out of scope), the current step is visually active (per shadcn's built-in active-item styling),
    future steps are visually muted/disabled — no new state machine, this just reads the same `step`
    value `App.tsx` already tracks.
  - Theme toggle (light/dark) docked at the bottom of the sidebar, using a shadcn `switch` or
    icon-button pair (sun/moon), wired to the dark-mode mechanism above.
  - Collapse is triggered by the sidebar's own built-in trigger/rail — shadcn's sidebar already ships
    a smooth width transition, no custom animation code needed.
- Main content area (`SidebarInset` or equivalent) renders whichever step component is active, same
  conditional-render structure `App.tsx` already has today.

## Shadcn adoption approach

The project (`frontend/`) is Tailwind v4 + Vite + React 19 with no existing `tailwind.config.*` and no
`components.json` — a clean target for `npx shadcn@latest init`, no conflicting legacy config to
reconcile.

Steps (detailed task breakdown belongs in the implementation plan, not here):

1. `npx shadcn@latest init` — creates `components.json`, `src/lib/utils.ts` (`cn()` helper), adds the
   `@/` path alias to `tsconfig.json` and `vite.config.ts`.
2. Replace `frontend/src/index.css`'s bare `@import "tailwindcss";` with the Mono-theme-derived
   `@theme inline` token block (light + dark + the two added semantic colors) described above.
3. Install components via `npx shadcn add <name>` as needed: `sidebar` (shell), `card` (Report's
   cost-config/scenario cards, Mapping's grouped sections), `table` (Mapping's sample-rows preview,
   Report's product drill-down), `badge` (exclusion-count chips, status pills), `progress` (Progress
   screen's bar), `select` (Mapping's 5 column dropdowns), `button`, `input`, `label` (forms
   throughout), `separator` (hairline dividers replacing ad hoc border classes), `skeleton` (loading
   states), `tooltip` (required once the sidebar collapses to icon-only — labels must still be
   reachable). (Exact list may narrow or grow slightly during implementation — this is the working set
   identified from today's 5 screens' actual needs, not a speculative superset.)
4. Each of the 5 step components is restyled to use these installed components in place of hand-rolled
   Tailwind JSX. Component *logic* (API calls, state, validation) is unchanged — this is a
   presentation-layer rewrite, not a behavior change.
5. `App.css` (leftover unused Vite-template boilerplate — hero/next-steps/spacer styles not referenced
   by any current component) is deleted as part of this work, not carried forward.

**Testing impact, called out explicitly**: shadcn components render different DOM (many wrap Radix
primitives) than the current hand-rolled markup. Existing Vitest + RTL tests for every step component
will need their queries/assertions updated to match the new DOM — this is expected, not a regression,
and the implementation plan must budget for it per screen rather than treating it as a drive-by fix.

## Per-screen application

Detailed per-screen mockups/markup are implementation-plan work, guided by `frontend-design`/
`impeccable` at that time — this spec fixes the system (tokens, shell, component base), not every
pixel of every screen. Known per-screen carry-overs and constraints:

- **Report**: keeps its existing information architecture (verdict → cost-config card → exclusion
  chips → scenario matrix → category table → paginated product drill-down) — only the visual language
  changes (Mono tokens/monospace type/sharp corners/sidebar shell replacing the old dark/emerald/
  rounded-2xl treatment), not the layout decisions from the Phase 5b spec.
- **Mapping**: the existing 5 mapping dropdowns + live preview + sample-rows table map naturally onto
  shadcn `select` + `table`.
- **Progress**: the existing progress bar / live status maps onto shadcn `progress`; `Loader2`
  (distinct from the sidebar's static `Activity` step icon) for the in-flight spinner state.
- No screen's information architecture changes in this phase — this is a re-skin plus a new shell, not
  a UX/flow redesign.

## Error handling

No new error states are introduced by this phase. Existing error handling per screen (inline errors,
the `ScopeEstimateStep`/`MappingStep` request-ordering guard pattern, `ReportStep`'s verdict
loading/error/empty states) is preserved as-is, just re-rendered through the new components/tokens.

## Testing

- Every existing Vitest + RTL suite (one per step component, plus `App.test.tsx`) is updated to match
  new shadcn-based DOM, not skipped or deleted.
- New: a small test (or tests) for the theme toggle — `prefers-color-scheme` fallback, `localStorage`
  override precedence, and the `dark` class actually landing on `<html>`.
- `npm run build` (not just `npm test`) remains a required last step per the standing project rule
  from Phase 5b/5c's final reviews — shadcn's TypeScript types and Tailwind v4's `@theme` syntax are
  exactly the kind of thing `tsc -b`/the Tailwind Vite plugin catch that Vitest/oxlint won't.
- A final whole-branch review pass explicitly re-invokes `impeccable`'s audit/critique workflow (or
  `frontend-design`'s calibration check) against the finished result, not just functional tests — this
  phase's deliverable is quality of visual outcome, and that needs a design-literate check, not only a
  green test suite.

## Out of scope for this phase

- Clicking backward in the sidebar to revisit a completed step (today's wizard is forward-only; the
  new sidebar shows step position but doesn't add backward navigation — that would be a flow change,
  not a re-skin).
- Any change to per-screen information architecture, validation rules, or API surface.
- Phase 6's original scope (`ShopifySource` sketch) — returns to the queue after this phase.
- A logo/brand mark beyond a text wordmark (no asset design in this phase).
- Animation/motion beyond the sidebar's built-in collapse transition and whatever minimal fades
  `frontend-design`/`impeccable` recommend during implementation — no bespoke motion system.
