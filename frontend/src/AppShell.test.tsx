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

    // A custom matcher, not `getByText('IS').closest('span')`: "IS" is itself
    // wrapped in its own leaf <span>, so `.closest('span')` on that match
    // returns itself (textContent "IS"), not the outer wrapper. This matcher
    // instead finds the one <span> whose OWN full textContent is the
    // complete title — uniquely the outermost wrapper, since no other <span>
    // in the tree (including the ancestor SidebarHeader, which is a <div>)
    // has that exact combined text.
    const header = screen.getByText(
      (content, element) => element?.tagName.toLowerCase() === 'span' && content === 'IS IT WORTH IT?'
    )
    expect(header).toBeInTheDocument()
  })
})
