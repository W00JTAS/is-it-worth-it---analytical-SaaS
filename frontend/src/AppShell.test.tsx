import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AppShell } from './AppShell'

describe('AppShell', () => {
  it('renders all 5 wizard steps with the current one marked active', () => {
    render(
      <AppShell currentStep="mapping">
        <p>content</p>
      </AppShell>
    )

    const labels = ['Upload', 'Mapping', 'Scope', 'Progress', 'Report']
    for (const label of labels) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument()
    }

    expect(screen.getByRole('button', { name: 'Mapping' })).toHaveAttribute('data-active', 'true')
    expect(screen.getByRole('button', { name: 'Upload' })).not.toHaveAttribute('data-active')
  })

  it('disables steps after the current one', () => {
    render(
      <AppShell currentStep="mapping">
        <p>content</p>
      </AppShell>
    )

    expect(screen.getByRole('button', { name: 'Scope' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Progress' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Report' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Upload' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Mapping' })).not.toBeDisabled()
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

    const toggle = screen.getByRole('button', { name: /theme/i })
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

    const trigger = document.querySelector('[data-slot="sidebar-trigger"]')
    if (!trigger) throw new Error('sidebar trigger not found')
    await user.click(trigger)

    // The trigger toggles the same lifted `open` state hover uses — clicking it once
    // from the default collapsed state must expand it.
    const sidebar = document.querySelector('[data-slot="sidebar"]')
    expect(sidebar).toHaveAttribute('data-state', 'expanded')
  })

  it('clicking the trigger pins the sidebar open — hovering away no longer collapses it', async () => {
    const user = userEvent.setup()
    const { container } = render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const trigger = document.querySelector('[data-slot="sidebar-trigger"]')
    const hoverRegion = container.querySelector('[data-slot="sidebar-container"]')
    const sidebar = container.querySelector('[data-slot="sidebar"]')
    if (!trigger || !hoverRegion || !sidebar) throw new Error('sidebar elements not found')

    await user.click(trigger)
    expect(sidebar).toHaveAttribute('data-state', 'expanded')

    await user.unhover(hoverRegion)
    expect(sidebar).toHaveAttribute('data-state', 'expanded')
  })

  it('expands on focus and collapses on blur, mirroring hover, when not pinned', async () => {
    const { container } = render(
      <AppShell currentStep="upload">
        <p>content</p>
      </AppShell>
    )

    const hoverRegion = container.querySelector('[data-slot="sidebar-container"]')
    const sidebar = container.querySelector('[data-slot="sidebar"]')
    if (!hoverRegion || !sidebar) throw new Error('sidebar elements not found')

    fireEvent.focus(hoverRegion)
    expect(sidebar).toHaveAttribute('data-state', 'expanded')

    fireEvent.blur(hoverRegion)
    expect(sidebar).toHaveAttribute('data-state', 'collapsed')
  })

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
})
