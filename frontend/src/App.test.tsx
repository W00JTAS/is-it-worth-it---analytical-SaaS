import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders the scaffold placeholder', () => {
    render(<App />)
    expect(screen.getByText('IS_IT_WORTH_IT — scaffold ready')).toBeInTheDocument()
  })
})
