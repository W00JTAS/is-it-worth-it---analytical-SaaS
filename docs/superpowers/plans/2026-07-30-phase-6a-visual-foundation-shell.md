# Phase 6a — Visual foundation + shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the design-token foundation (shadcn/ui "Mono" theme + custom success/warning
accents, Geist Mono font, light-default/dark-toggle mechanism) and a new wizard-wide shell
(collapsible icon sidebar with the 5 wizard steps), replacing `App.tsx`'s bare full-screen step swap
— without touching any individual step screen's internal markup yet.

**Architecture:** Adopt shadcn/ui as an owned-source component library (`npx shadcn add`, edited
in-repo, not a black-box dependency) on top of the existing Tailwind v4 + Vite + React 19 stack.
Tokens live in `frontend/src/index.css` as CSS custom properties, consumed both by shadcn components
and (in later plans) by the restyled step screens. A small `useTheme` hook manages the light/dark
toggle independently of shadcn, since Vite has no built-in theme provider. `AppShell` wraps the
existing step-swap logic from `App.tsx` without changing that logic.

**Tech Stack:** React 19, Vite 8, Tailwind v4, shadcn/ui v4 (new-york style, "Mono" theme as base),
Radix UI (via shadcn), lucide-react, `@fontsource/geist-mono`, Vitest + React Testing Library.

## Global Constraints

- This is **Plan 1 of a multi-plan sequence** implementing
  `docs/superpowers/specs/2026-07-30-phase-6-visual-redesign-design.md`. Per-screen restyling
  (Upload, Mapping, Scope+Estimate, Progress, Report) is **out of scope for this plan** — those are
  separate follow-up plans, written after this one lands, so their code can reference the actual
  shell/tokens this plan produces rather than a still-hypothetical version of them.
- No change to any step component's *logic* (API calls, validation, state) — this plan only touches
  `App.tsx`'s wrapper, plus new shell/theme files.
- `npm run build` (not just `npm test`) is a required verification step on every task that touches
  TypeScript or Tailwind config — this is a standing rule from this project's Phase 5b/5c reviews,
  where `tsc -b`/the Tailwind Vite plugin caught real errors that `vitest`/`oxlint` missed.
- Light is the default color mode; dark is opt-in via toggle. Never ship dark-only or light-only.
- All new/edited source in `frontend/`; no backend changes in this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/components.json` | shadcn CLI config (created by `init`, not hand-written) |
| `frontend/src/lib/utils.ts` | `cn()` classname helper (created by `init`) |
| `frontend/src/hooks/use-mobile.ts` | Mobile-breakpoint hook (created by `shadcn add sidebar`, a dependency of the sidebar component) |
| `frontend/src/components/ui/*.tsx` | shadcn-owned component source: `sidebar.tsx`, `button.tsx`, `input.tsx`, `separator.tsx`, `sheet.tsx`, `skeleton.tsx`, `tooltip.tsx` (all installed transitively via `shadcn add sidebar`) |
| `frontend/src/index.css` | Design tokens: Mono-theme light/dark CSS variables, added `--success`/`--warning`, Geist Mono font, Tailwind v4 `@theme inline` mapping |
| `frontend/src/theme/useTheme.ts` | Light/dark state: reads `prefers-color-scheme` + `localStorage`, toggles the `dark` class on `<html>`, persists on change |
| `frontend/src/theme/useTheme.test.ts` | Tests for the above |
| `frontend/src/wizardSteps.ts` | `WizardStep` type + ordered step metadata (id, label, icon) shared between `App.tsx` and `AppShell.tsx` |
| `frontend/src/AppShell.tsx` | The sidebar shell: 5 step nav items with icons/tooltips, active/future-step styling, theme toggle |
| `frontend/src/AppShell.test.tsx` | Tests for the above |
| `frontend/src/App.tsx` | Modified: wraps step-swap in `<AppShell>`, imports `WizardStep` from `wizardSteps.ts` instead of declaring it locally |
| `frontend/src/test/setup.ts` | Modified: adds a global `window.matchMedia` mock (needed by both `useTheme` and shadcn's internal `useIsMobile`) |
| `frontend/src/App.css` | **Deleted** — confirmed unused (not imported anywhere; leftover Vite template boilerplate) |

---

### Task 1: shadcn scaffolding + design tokens

**Files:**
- Create: `frontend/components.json`, `frontend/src/lib/utils.ts` (via CLI)
- Create: `frontend/src/components/ui/sidebar.tsx`, `button.tsx`, `input.tsx`, `separator.tsx`,
  `sheet.tsx`, `skeleton.tsx`, `tooltip.tsx`, `frontend/src/hooks/use-mobile.ts` (via CLI)
- Modify: `frontend/src/index.css`, `frontend/package.json`
- Delete: `frontend/src/App.css`

**Interfaces:**
- Produces: CSS custom properties consumed by every later task — `--background`, `--foreground`,
  `--card`, `--muted`, `--muted-foreground`, `--border`, `--primary`, `--destructive`, `--success`,
  `--warning`, `--sidebar*`, mapped into Tailwind utility classes (`bg-background`, `text-success`,
  etc.) via `@theme inline`. Also produces the `dark` custom variant (`@custom-variant dark
  (&:is(.dark *));`) that `useTheme` (Task 2) toggles via a class on `<html>`.
- Consumes: nothing from earlier tasks (this is the first task).

- [ ] **Step 1: Run the shadcn CLI init**

From `frontend/`:

```bash
npx shadcn@latest init
```

If prompted interactively, answer: style **New York**, base color **Neutral**, CSS variables **Yes**.
(The exact base color barely matters — Step 5 below replaces the generated token block entirely.)
Confirm it created `components.json` and `src/lib/utils.ts`, and added a `@/*` path alias to
`tsconfig.json`/`tsconfig.app.json` and `vite.config.ts`.

- [ ] **Step 2: Install the sidebar component and its dependencies**

```bash
npx shadcn add sidebar
```

This pulls in `button`, `input`, `separator`, `sheet`, `skeleton`, and `tooltip` automatically (the
sidebar component imports all of them) plus their Radix/CVA dependencies into `package.json`. Confirm
`frontend/src/components/ui/sidebar.tsx` and the six sibling files now exist, and
`frontend/src/hooks/use-mobile.ts` was created.

- [ ] **Step 3: Add the font and icon packages**

```bash
npm install lucide-react @fontsource/geist-mono
```

- [ ] **Step 4: Replace `frontend/src/index.css` with the token set**

Replace the entire file content with:

```css
@import "tailwindcss";
@import "@fontsource/geist-mono/400.css";
@import "@fontsource/geist-mono/500.css";
@import "@fontsource/geist-mono/600.css";
@import "@fontsource/geist-mono/700.css";

@custom-variant dark (&:is(.dark *));

:root {
  --radius: 0rem;

  --background: #ffffff;
  --foreground: #0a0a0a;
  --card: #ffffff;
  --card-foreground: #0a0a0a;
  --popover: #ffffff;
  --popover-foreground: #0a0a0a;
  --primary: #737373;
  --primary-foreground: #fafafa;
  --secondary: #f5f5f5;
  --secondary-foreground: #171717;
  --muted: #f5f5f5;
  --muted-foreground: #717171;
  --accent: #f5f5f5;
  --accent-foreground: #171717;
  --destructive: #e7000b;
  --destructive-foreground: #f5f5f5;
  --border: #e5e5e5;
  --input: #e5e5e5;
  --ring: #a1a1a1;

  --success: #0d8f4f;
  --warning: #a3760a;

  --sidebar: #fafafa;
  --sidebar-foreground: #0a0a0a;
  --sidebar-primary: #171717;
  --sidebar-primary-foreground: #fafafa;
  --sidebar-accent: #f5f5f5;
  --sidebar-accent-foreground: #171717;
  --sidebar-border: #e5e5e5;
  --sidebar-ring: #a1a1a1;

  --font-sans: "Geist Mono", ui-monospace, monospace;
  --font-mono: "Geist Mono", ui-monospace, monospace;
}

.dark {
  --background: #0a0a0a;
  --foreground: #fafafa;
  --card: #191919;
  --card-foreground: #fafafa;
  --popover: #262626;
  --popover-foreground: #fafafa;
  --primary: #737373;
  --primary-foreground: #fafafa;
  --secondary: #262626;
  --secondary-foreground: #fafafa;
  --muted: #262626;
  --muted-foreground: #a1a1a1;
  --accent: #404040;
  --accent-foreground: #fafafa;
  --destructive: #ff6467;
  --destructive-foreground: #262626;
  --border: #383838;
  --input: #525252;
  --ring: #737373;

  --success: #39d98a;
  --warning: #e0b84d;

  --sidebar: #171717;
  --sidebar-foreground: #fafafa;
  --sidebar-primary: #fafafa;
  --sidebar-primary-foreground: #171717;
  --sidebar-accent: #262626;
  --sidebar-accent-foreground: #fafafa;
  --sidebar-border: #ffffff;
  --sidebar-ring: #525252;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  --color-success: var(--success);
  --color-warning: var(--warning);

  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);

  --font-sans: var(--font-sans);
  --font-mono: var(--font-mono);
}

@layer base {
  body {
    @apply bg-background text-foreground;
    font-family: var(--font-sans);
  }
}
```

(If `npx shadcn add sidebar` in Step 2 already appended its own component-specific CSS layer rules
below `@theme inline` — some registry versions add a small `@layer base` block for scrollbar/utility
resets — keep those, just replacing the color/font token values with the block above rather than
deleting the whole file blindly.)

- [ ] **Step 5: Delete the unused legacy stylesheet**

```bash
git rm frontend/src/App.css
```

(Already confirmed unused — not imported by any `.tsx`/`.ts` file in the project.)

- [ ] **Step 6: Verify the build**

```bash
cd frontend && npm run build
```

Expected: succeeds with no TypeScript or Tailwind errors. This is the verification for this task —
there is no new runtime behavior yet (no component consumes the new tokens until Task 3), so
correctness here means "the toolchain accepts the new config," not a new passing test.

- [ ] **Step 7: Run the existing test suite**

```bash
npm test
```

Expected: all existing tests still pass unchanged (no component was touched yet).

- [ ] **Step 8: Commit**

```bash
git add frontend/components.json frontend/src/lib frontend/src/components frontend/src/hooks \
  frontend/src/index.css frontend/package.json frontend/package-lock.json
git rm frontend/src/App.css 2>/dev/null || true
git commit -m "Add shadcn/ui scaffolding and Mono-theme design tokens"
```

---

### Task 2: `useTheme` — light/dark mode logic

**Files:**
- Create: `frontend/src/theme/useTheme.ts`
- Create: `frontend/src/theme/useTheme.test.ts`
- Modify: `frontend/src/test/setup.ts`

**Interfaces:**
- Consumes: nothing new from Task 1 besides the `dark` custom variant already wired into
  `index.css` (this task only ever writes `document.documentElement.classList`, it doesn't import CSS).
- Produces: `useTheme(): { theme: 'light' | 'dark'; setTheme: (t: 'light' | 'dark') => void;
  toggleTheme: () => void }` — the exact shape `AppShell` (Task 3) consumes.

- [ ] **Step 1: Add a global `matchMedia` mock to the test setup file**

Replace the content of `frontend/src/test/setup.ts` with:

```ts
import '@testing-library/jest-dom/vitest'
import { beforeEach, vi } from 'vitest'

beforeEach(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
})
```

This gives every test a default "no dark preference, not mobile" `matchMedia`, overridable per-test.
It is needed both by this task's `useTheme` and by shadcn's internal `useIsMobile` hook (consumed by
the `Sidebar` component in Task 3/4) — jsdom has no native `matchMedia` implementation.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/theme/useTheme.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useTheme } from './useTheme'

// RTL's cleanup() unmounts components but never touches document.documentElement —
// without this, a `dark` class set by one test leaks into the next.
afterEach(() => {
  document.documentElement.classList.remove('dark')
})

function mockMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

describe('useTheme', () => {
  it('defaults to light when there is no stored preference and the system prefers light', () => {
    window.localStorage.clear()
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  it('defaults to dark when there is no stored preference and the system prefers dark', () => {
    window.localStorage.clear()
    mockMatchMedia(true)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  it('prefers a stored localStorage value over the system preference', () => {
    window.localStorage.setItem('isItWorthIt.theme', 'dark')
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())

    expect(result.current.theme).toBe('dark')
  })

  it('toggleTheme flips the theme, updates the dark class, and persists to localStorage', () => {
    window.localStorage.clear()
    mockMatchMedia(false)

    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')

    act(() => {
      result.current.toggleTheme()
    })

    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(window.localStorage.getItem('isItWorthIt.theme')).toBe('dark')
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
npm test -- useTheme
```

Expected: FAIL — `Cannot find module './useTheme'`.

- [ ] **Step 4: Implement `useTheme`**

Create `frontend/src/theme/useTheme.ts`:

```ts
import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'isItWorthIt.theme'

function getStoredTheme(): Theme | null {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' ? stored : null
}

function getSystemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme() ?? getSystemTheme())

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    setThemeState(next)
  }, [])

  const toggleTheme = useCallback(() => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setTheme])

  return { theme, setTheme, toggleTheme }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm test -- useTheme
```

Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/theme frontend/src/test/setup.ts
git commit -m "Add useTheme hook for light/dark mode"
```

---

### Task 3: `AppShell` — collapsible icon sidebar

**Files:**
- Create: `frontend/src/wizardSteps.ts`
- Create: `frontend/src/AppShell.tsx`
- Create: `frontend/src/AppShell.test.tsx`

**Interfaces:**
- Consumes: `useTheme()` from Task 2 (exact shape above); `Sidebar`, `SidebarContent`,
  `SidebarFooter`, `SidebarGroup`, `SidebarGroupContent`, `SidebarHeader`, `SidebarInset`,
  `SidebarMenu`, `SidebarMenuButton`, `SidebarMenuItem`, `SidebarProvider`, `SidebarRail` from
  `@/components/ui/sidebar` (Task 1); `Button` from `@/components/ui/button` (Task 1).
- Produces: `WizardStep` type (`'upload' | 'mapping' | 'scope' | 'progress' | 'report'`) and
  `WIZARD_STEPS` metadata array from `wizardSteps.ts` — Task 4 imports `WizardStep` from here instead
  of declaring it inline in `App.tsx`. `AppShell({ currentStep, children }): JSX.Element` — the exact
  props Task 4 passes.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/AppShell.test.tsx`:

```tsx
import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from './AppShell'

// useTheme's effect never removes the `dark` class on unmount, and RTL's cleanup()
// doesn't touch document.documentElement — reset it so test order can't matter.
afterEach(() => {
  document.documentElement.classList.remove('dark')
})

describe('AppShell', () => {
  it('renders all 5 wizard steps with the current one marked active', () => {
    render(
      <AppShell currentStep="mapping">
        <p>content</p>
      </AppShell>
    )

    const labels = ['Upload', 'Mapowanie', 'Zakres', 'Postęp', 'Raport']
    for (const label of labels) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }

    expect(screen.getByRole('button', { name: 'Mapowanie' })).toHaveAttribute('data-active', 'true')
    expect(screen.getByRole('button', { name: 'Upload' })).toHaveAttribute('data-active', 'false')
  })

  it('disables steps after the current one', () => {
    render(
      <AppShell currentStep="mapping">
        <p>content</p>
      </AppShell>
    )

    expect(screen.getByRole('button', { name: 'Zakres' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Postęp' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Raport' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Upload' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Mapowanie' })).not.toBeDisabled()
  })

  it('renders children inside the content area', () => {
    render(
      <AppShell currentStep="upload">
        <p>step content goes here</p>
      </AppShell>
    )

    expect(screen.getByText('step content goes here')).toBeInTheDocument()
  })

  it('toggles the theme when the theme button is clicked', async () => {
    const user = userEvent.setup()
    render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const toggle = screen.getByRole('button', { name: /motyw/i })
    expect(document.documentElement.classList.contains('dark')).toBe(false)

    await user.click(toggle)

    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm test -- AppShell
```

Expected: FAIL — `Cannot find module './AppShell'`.

- [ ] **Step 3: Create the wizard step metadata**

Create `frontend/src/wizardSteps.ts`:

```ts
import { Activity, BarChart3, Columns3, Target, Upload, type LucideIcon } from 'lucide-react'

export type WizardStep = 'upload' | 'mapping' | 'scope' | 'progress' | 'report'

export interface WizardStepMeta {
  id: WizardStep
  label: string
  icon: LucideIcon
}

export const WIZARD_STEPS: readonly WizardStepMeta[] = [
  { id: 'upload', label: 'Upload', icon: Upload },
  { id: 'mapping', label: 'Mapowanie', icon: Columns3 },
  { id: 'scope', label: 'Zakres', icon: Target },
  { id: 'progress', label: 'Postęp', icon: Activity },
  { id: 'report', label: 'Raport', icon: BarChart3 },
]
```

- [ ] **Step 4: Implement `AppShell`**

Create `frontend/src/AppShell.tsx`:

```tsx
import type { ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
} from '@/components/ui/sidebar'
import { useTheme } from './theme/useTheme'
import { WIZARD_STEPS, type WizardStep } from './wizardSteps'

interface AppShellProps {
  currentStep: WizardStep
  children: ReactNode
}

export function AppShell({ currentStep, children }: AppShellProps) {
  const { theme, toggleTheme } = useTheme()
  const currentIndex = WIZARD_STEPS.findIndex((step) => step.id === currentStep)

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <span className="px-2 py-1 text-sm font-semibold tracking-tight">IS IT WORTH IT</span>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {WIZARD_STEPS.map((step, index) => (
                  <SidebarMenuItem key={step.id}>
                    <SidebarMenuButton
                      isActive={step.id === currentStep}
                      disabled={index > currentIndex}
                      tooltip={step.label}
                    >
                      <step.icon />
                      <span>{step.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <Button
            variant="ghost"
            size="icon"
            aria-label={theme === 'dark' ? 'Przełącz na jasny motyw' : 'Przełącz na ciemny motyw'}
            onClick={toggleTheme}
          >
            {theme === 'dark' ? <Sun /> : <Moon />}
          </Button>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset>{children}</SidebarInset>
    </SidebarProvider>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm test -- AppShell
```

Expected: PASS (4 tests).

- [ ] **Step 6: Run the full test suite and build**

```bash
npm test && npm run build
```

Expected: everything still passes (Task 4 hasn't wired `AppShell` into `App.tsx` yet, so no other
test is affected).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/wizardSteps.ts frontend/src/AppShell.tsx frontend/src/AppShell.test.tsx
git commit -m "Add AppShell: collapsible icon sidebar with wizard steps"
```

---

### Task 4: Wire `AppShell` into `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `AppShell` and `WizardStep` from Task 3, exactly as defined above.
- Produces: nothing new — this task only changes how `App.tsx` renders, not its exported surface
  (`export default App` unchanged).

- [ ] **Step 1: Modify `App.tsx`**

Replace the full content of `frontend/src/App.tsx`:

```tsx
import { useState } from 'react'
import { AppShell } from './AppShell'
import { UploadStep } from './steps/UploadStep'
import { MappingStep } from './steps/MappingStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'
import type { ColumnMapping } from './api/types'
import type { WizardStep } from './wizardSteps'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [columnMapping, setColumnMapping] = useState<ColumnMapping | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <AppShell currentStep={step}>
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('mapping')
          }}
        />
      )}
      {step === 'mapping' && file && (
        <MappingStep
          file={file}
          onConfirmed={(mapping) => {
            setColumnMapping(mapping)
            setStep('scope')
          }}
        />
      )}
      {step === 'scope' && file && columnMapping && (
        <ScopeEstimateStep
          file={file}
          columnMapping={columnMapping}
          onStarted={(id) => {
            setScanId(id)
            setStep('progress')
          }}
        />
      )}
      {step === 'progress' && scanId && (
        <ProgressStep scanId={scanId} onDone={() => setStep('report')} />
      )}
      {step === 'report' && scanId && <ReportStep scanId={scanId} />}
    </AppShell>
  )
}

export default App
```

- [ ] **Step 2: Run the existing `App.test.tsx` suite**

```bash
npm test -- App.test
```

Expected: PASS, unchanged (both existing scenarios still query by heading/button role, which
`AppShell`'s wrapper doesn't interfere with). If a query unexpectedly matches more than one element
(e.g. a future ambiguity between a sidebar nav label and a step heading), disambiguate the *test*
query with a more specific role/name — do not change `AppShell`'s labels to work around it.

- [ ] **Step 3: Run the full suite, lint, and build**

```bash
npm test && npm run lint && npm run build
```

Expected: all pass. This is the final verification for Phase 6a as a whole — foundation and shell are
now live for every screen, with no step's internal markup touched yet.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "Wire AppShell into App.tsx"
```

---

## Self-Review Notes

- **Spec coverage**: this plan implements the "Design tokens," "Shell," and the CLI-init portion of
  "Shadcn adoption approach" sections of the Phase 6 spec. It deliberately does **not** cover "Per-screen
  application" — that's follow-up plans (Phase 6b onward), written after this lands.
  Deliberately out of scope here: backward navigation via the sidebar (spec explicitly excludes it).
- **Type consistency checked**: `WizardStep` is defined once (`wizardSteps.ts`), imported by both
  `AppShell.tsx` and `App.tsx` — no duplicate/divergent definition. `useTheme`'s return shape
  (`theme`, `setTheme`, `toggleTheme`) matches exactly what `AppShell` destructures (`theme`,
  `toggleTheme` — `setTheme` unused by `AppShell` but kept on the hook's public surface since it's a
  reasonable general-purpose hook API, not dead code with no caller: `toggleTheme` itself calls it).
- **No placeholders**: every step has literal, complete code — no "TBD"/"similar to Task N" refs.
