import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
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
})
