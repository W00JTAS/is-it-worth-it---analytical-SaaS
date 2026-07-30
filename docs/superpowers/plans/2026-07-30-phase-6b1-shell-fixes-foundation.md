# Phase 6b-1 — Shell UX fixes + PaginatedList foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the sidebar's non-functional "auto-hide" (make it genuinely hover-driven), wrap the
app's content in a themed custom scrollbar, and build a reusable `PaginatedList` component that
Phase 6b-2 will use to fix Mapping's and Scope+Estimate's unbounded warnings lists.

**Architecture:** `AppShell`'s `SidebarProvider` becomes a controlled component (`open`/`onOpenChange`
lifted into `AppShell`'s own state) so hover handlers on the `Sidebar` element can drive it directly,
alongside the existing click-based trigger/rail. `PaginatedList` is a small, generic, purely
client-side component with no dependency on any specific screen — Phase 6b-2 wires it into Mapping
and Scope+Estimate.

**Tech Stack:** React 19, Vite 8, Tailwind v4, shadcn/ui (Radix-based, already installed), Vitest +
React Testing Library.

## Global Constraints

- This is **Plan 1 of the Phase 6b sequence** (per-screen restyling itself is Phase 6b-2 onward,
  written after this lands). Implements `docs/superpowers/specs/2026-07-30-phase-6b-per-screen-restyle-design.md`.
- No debounce/delay on the hover interaction (explicit YAGNI call in the spec).
- `npm run build` is a required verification step on every task, alongside `npm test`.
- No change to any step screen's markup in this plan — `PaginatedList` is built and tested in
  isolation, not yet wired into `MappingStep`/`ScopeEstimateStep` (that's Phase 6b-2).

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/src/components/ui/scroll-area.tsx`, `pagination.tsx` | New shadcn components, installed via CLI |
| `frontend/src/components/PaginatedList.tsx` | New: generic, reusable paginated list (10/page callers pass explicitly) |
| `frontend/src/components/PaginatedList.test.tsx` | Tests for the above |
| `frontend/src/AppShell.tsx` | Modified: controlled sidebar `open` state, hover handlers, `ScrollArea` wrapping the inset content |
| `frontend/src/AppShell.test.tsx` | Modified: tests for hover-driven expand/collapse, existing tests preserved |

---

### Task 1: `PaginatedList` component

**Files:**
- Create: `frontend/src/components/ui/pagination.tsx` (via `npx shadcn add pagination` — pulls in
  `button` styling helpers, already installed)
- Create: `frontend/src/components/PaginatedList.tsx`
- Test: `frontend/src/components/PaginatedList.test.tsx`

**Interfaces:**
- Consumes: nothing from this branch's other tasks.
- Produces: `PaginatedList<T>({ items, pageSize, renderItem, emptyState? })` — the exact generic
  component signature Phase 6b-2's `MappingStep`/`ScopeEstimateStep` will import and use.

- [ ] **Step 1: Install the shadcn pagination component**

```bash
cd frontend && npx shadcn add pagination
```

Confirm `frontend/src/components/ui/pagination.tsx` now exists, exporting `Pagination`,
`PaginationContent`, `PaginationItem`, `PaginationLink`, `PaginationPrevious`, `PaginationNext`,
`PaginationEllipsis`.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/components/PaginatedList.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PaginatedList } from './PaginatedList'

describe('PaginatedList', () => {
  it('renders only the first page of items when there are more than pageSize', () => {
    const items = Array.from({ length: 25 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByText('item-1')).toBeInTheDocument()
    expect(screen.getByText('item-10')).toBeInTheDocument()
    expect(screen.queryByText('item-11')).not.toBeInTheDocument()
  })

  it('hides pagination controls when everything fits on one page', () => {
    const items = ['a', 'b', 'c']
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.queryByRole('navigation', { name: /pagination/i })).not.toBeInTheDocument()
  })

  it('shows pagination controls and navigates to the next page', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 25 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByRole('navigation', { name: /pagination/i })).toBeInTheDocument()

    await user.click(screen.getByLabelText('Go to next page'))

    expect(screen.getByText('item-11')).toBeInTheDocument()
    expect(screen.getByText('item-20')).toBeInTheDocument()
    expect(screen.queryByText('item-1')).not.toBeInTheDocument()
  })

  it('disables Previous on the first page and Next on the last page', async () => {
    const user = userEvent.setup()
    const items = Array.from({ length: 15 }, (_, i) => `item-${i + 1}`)
    render(<PaginatedList items={items} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByLabelText('Go to previous page')).toHaveAttribute('aria-disabled', 'true')

    await user.click(screen.getByLabelText('Go to next page'))

    expect(screen.getByText('item-15')).toBeInTheDocument()
    expect(screen.getByLabelText('Go to next page')).toHaveAttribute('aria-disabled', 'true')
  })

  it('resets to page 1 when the items array changes', async () => {
    const user = userEvent.setup()
    const itemsA = Array.from({ length: 25 }, (_, i) => `a-${i + 1}`)
    const itemsB = Array.from({ length: 25 }, (_, i) => `b-${i + 1}`)
    const { rerender } = render(
      <PaginatedList items={itemsA} pageSize={10} renderItem={(item) => <span>{item}</span>} />
    )

    await user.click(screen.getByLabelText('Go to next page'))
    expect(screen.getByText('a-11')).toBeInTheDocument()

    rerender(<PaginatedList items={itemsB} pageSize={10} renderItem={(item) => <span>{item}</span>} />)

    expect(screen.getByText('b-1')).toBeInTheDocument()
    expect(screen.queryByText('b-11')).not.toBeInTheDocument()
  })

  it('renders the empty state when items is empty', () => {
    render(
      <PaginatedList
        items={[]}
        pageSize={10}
        renderItem={(item) => <span>{String(item)}</span>}
        emptyState={<p>Brak wpisów</p>}
      />
    )

    expect(screen.getByText('Brak wpisów')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
npm test -- PaginatedList
```

Expected: FAIL — `Cannot find module './PaginatedList'`.

- [ ] **Step 4: Implement `PaginatedList`**

Create `frontend/src/components/PaginatedList.tsx`:

```tsx
import { useEffect, useState, type ReactNode } from 'react'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'

interface PaginatedListProps<T> {
  items: readonly T[]
  pageSize: number
  renderItem: (item: T, index: number) => ReactNode
  emptyState?: ReactNode
}

export function PaginatedList<T>({ items, pageSize, renderItem, emptyState }: PaginatedListProps<T>) {
  const [page, setPage] = useState(1)
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize))

  useEffect(() => {
    setPage(1)
  }, [items])

  if (items.length === 0) {
    return emptyState ?? null
  }

  const start = (page - 1) * pageSize
  const pageItems = items.slice(start, start + pageSize)
  const isFirstPage = page === 1
  const isLastPage = page === pageCount

  return (
    <div className="space-y-3">
      <ul className="space-y-1">
        {pageItems.map((item, index) => (
          <li key={start + index}>{renderItem(item, start + index)}</li>
        ))}
      </ul>
      {pageCount > 1 && (
        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  setPage((current) => Math.max(1, current - 1))
                }}
                aria-disabled={isFirstPage}
                className={isFirstPage ? 'pointer-events-none opacity-50' : undefined}
              />
            </PaginationItem>
            <PaginationItem>
              <span className="px-3 text-sm text-muted-foreground">
                {page} / {pageCount}
              </span>
            </PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                onClick={(event) => {
                  event.preventDefault()
                  setPage((current) => Math.min(pageCount, current + 1))
                }}
                aria-disabled={isLastPage}
                className={isLastPage ? 'pointer-events-none opacity-50' : undefined}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm test -- PaginatedList
```

Expected: PASS (6 tests).

- [ ] **Step 6: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ui/pagination.tsx frontend/src/components/PaginatedList.tsx \
  frontend/src/components/PaginatedList.test.tsx frontend/package.json frontend/package-lock.json
git commit -m "Add PaginatedList: generic client-side paginated list"
```

---

### Task 2: Sidebar hover behavior + themed scrollbar

**Files:**
- Create: `frontend/src/components/ui/scroll-area.tsx` (via `npx shadcn add scroll-area`)
- Modify: `frontend/src/AppShell.tsx`
- Modify: `frontend/src/AppShell.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 (independent file).
- Produces: no new exports — `AppShell`'s props (`{ currentStep, children }`) are unchanged, only its
  internal behavior changes.

- [ ] **Step 1: Install the shadcn scroll-area component**

```bash
cd frontend && npx shadcn add scroll-area
```

- [ ] **Step 2: Write the failing tests**

Replace `frontend/src/AppShell.test.tsx`'s content with (adds 3 new tests for hover behavior at the
end, keeps all 4 existing tests unchanged, updates only the two `data-active` assertions that
Phase 6a's final fix wave already changed — those stay as-is):

```tsx
import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from './AppShell'

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
    expect(screen.getByRole('button', { name: 'Upload' })).not.toHaveAttribute('data-active')
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

  it('starts collapsed', () => {
    const { container } = render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const sidebar = container.querySelector('[data-slot="sidebar"]')
    expect(sidebar).toHaveAttribute('data-state', 'collapsed')
  })

  it('expands on mouse enter and collapses again on mouse leave', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const hoverRegion = container.querySelector('[data-slot="sidebar-container"]')
    const sidebar = container.querySelector('[data-slot="sidebar"]')
    if (!hoverRegion || !sidebar) throw new Error('sidebar elements not found')

    await user.hover(hoverRegion)
    expect(sidebar).toHaveAttribute('data-state', 'expanded')

    await user.unhover(hoverRegion)
    expect(sidebar).toHaveAttribute('data-state', 'collapsed')
  })

  it('still expands via the mobile trigger button independently of hover', async () => {
    const user = userEvent.setup()
    render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const trigger = screen.getByRole('button', { name: /toggle sidebar/i })
    await user.click(trigger)

    // The trigger toggles the same lifted `open` state hover uses — clicking it once
    // from the default collapsed state must expand it.
    const sidebar = document.querySelector('[data-slot="sidebar"]')
    expect(sidebar).toHaveAttribute('data-state', 'expanded')
  })
})
```

- [ ] **Step 3: Run the tests to verify the 3 new ones fail**

```bash
npm test -- AppShell
```

Expected: the 4 pre-existing tests still pass; "starts collapsed", "expands on mouse enter...", and
"still expands via the mobile trigger..." FAIL (current `AppShell` always starts expanded with
uncontrolled state).

- [ ] **Step 4: Update `AppShell.tsx`**

Replace `frontend/src/AppShell.tsx`'s content with:

```tsx
import { useState, type ReactNode } from 'react'
import { Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
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
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useTheme } from './theme/useTheme'
import { WIZARD_STEPS, type WizardStep } from './wizardSteps'

interface AppShellProps {
  currentStep: WizardStep
  children: ReactNode
}

export function AppShell({ currentStep, children }: AppShellProps) {
  const { theme, toggleTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const currentIndex = WIZARD_STEPS.findIndex((step) => step.id === currentStep)

  return (
    <TooltipProvider>
      <SidebarProvider open={open} onOpenChange={setOpen}>
        <Sidebar
          collapsible="icon"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
        >
          <SidebarHeader>
            <span className="px-2 py-1 text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">IS IT WORTH IT</span>
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
        <SidebarInset>
          <ScrollArea className="h-svh">
            <header className="flex items-center gap-2 p-2 md:hidden">
              <SidebarTrigger />
            </header>
            {children}
          </ScrollArea>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm test -- AppShell
```

Expected: PASS (7 tests). `frontend/src/hooks/use-mobile.ts`'s `useIsMobile` checks
`window.innerWidth < 768`; jsdom's default `window.innerWidth` is 1024, so `isMobile` is `false` by
default and `Sidebar` renders its desktop branch (the one with `data-slot="sidebar-container"`) —
confirmed by reading the hook, not assumed. If this ever fails with "sidebar elements not found," the
jsdom default changed or something set `window.innerWidth` earlier in the test run; don't work around
it blindly, confirm what actually changed first.

- [ ] **Step 6: Run the full suite and build**

```bash
npm test && npm run build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ui/scroll-area.tsx frontend/src/AppShell.tsx \
  frontend/src/AppShell.test.tsx frontend/package.json frontend/package-lock.json
git commit -m "Make sidebar hover-driven; wrap content in a themed scrollbar"
```

---

## Self-Review Notes

- **Spec coverage**: implements the spec's "Sidebar hover behavior" and "Scrollbar" decisions in
  full, and the `PaginatedList` component completely (its two call sites are Phase 6b-2's job, not
  this plan's — the spec's own "Warnings/problem lists" decision names the component but wiring it
  into `MappingStep`/`ScopeEstimateStep` is explicitly a per-screen restyle task).
- **Type consistency checked**: `PaginatedList<T>`'s prop names (`items`, `pageSize`, `renderItem`,
  `emptyState`) match exactly what the spec's own interface sketch defined — Phase 6b-2's plan must
  use these same names.
- **No placeholders**: every step has complete, literal code.
- **Known risk flagged inline** (Task 2 Step 5): jsdom's `useIsMobile` behavior at test time is
  asserted, not assumed — if the hover test can't find the expected element, the plan tells the
  engineer to investigate rather than force a workaround.
