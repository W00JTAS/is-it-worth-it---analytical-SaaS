import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReportStep } from './ReportStep'
import * as client from '../api/client'

const SUMMARY = {
  counts: { total: 10, computable: 8, not_checked: 0, no_offer: 1, currency_mismatch: 0, anomaly: 1 },
  category_table: [
    { category: 'Elektronika', computable_count: 8, excluded_count: 2, avg_margin_pct: '0.1200' },
  ],
  scenario_matrix: [
    { scenario_pct: '-0.10', avg_margin_pct: '0.0200', profitable_count: 5 },
    { scenario_pct: '-0.05', avg_margin_pct: '0.0700', profitable_count: 6 },
    { scenario_pct: '0.00', avg_margin_pct: '0.1200', profitable_count: 7 },
    { scenario_pct: '0.05', avg_margin_pct: '0.1700', profitable_count: 8 },
  ],
}

beforeEach(() => {
  localStorage.clear()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('ReportStep', () => {
  it('loads the summary on mount using the default cost config and shows the verdict', async () => {
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('+12.0%')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledWith('scan-1', {
      commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
    })
  })

  it('shows the exclusion counts as chips, only for non-zero counts', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('1 bez oferty')).toBeInTheDocument()
    expect(screen.getByText('1 oflagowanych')).toBeInTheDocument()
    expect(screen.queryByText(/innej waluty/)).not.toBeInTheDocument()
    expect(screen.queryByText(/nie sprawdzono/)).not.toBeInTheDocument()
  })

  it('shows the scenario matrix and category table', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    await screen.findByText('+12.0%')
    expect(screen.getByText('5 rentownych')).toBeInTheDocument()
    expect(screen.getByText('Elektronika')).toBeInTheDocument()
  })

  it('recalculates with edited cost config when Przelicz is clicked, and persists to localStorage', async () => {
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('+12.0%')

    const commissionInput = screen.getByLabelText('Prowizja')
    await userEvent.clear(commissionInput)
    await userEvent.type(commissionInput, '0.20')
    await userEvent.click(screen.getByRole('button', { name: 'Przelicz' }))

    await waitFor(() =>
      expect(spy).toHaveBeenLastCalledWith('scan-1', {
        commissionPct: '0.2', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
      }),
    )
    expect(JSON.parse(localStorage.getItem('isItWorthIt.costConfig')!)).toEqual({
      commissionPct: '0.2', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05',
    })
  })

  it('loads persisted cost config from localStorage on mount', async () => {
    localStorage.setItem(
      'isItWorthIt.costConfig',
      JSON.stringify({ commissionPct: '0.25', shippingCost: '10.00', vatPct: '0.23', returnsPct: '0.03' }),
    )
    const spy = vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    render(<ReportStep scanId="scan-1" />)

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith('scan-1', {
        commissionPct: '0.25', shippingCost: '10.00', vatPct: '0.23', returnsPct: '0.03',
      }),
    )
  })

  it('shows an empty state when there are no computable products', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue({
      counts: { total: 3, computable: 0, not_checked: 0, no_offer: 3, currency_mismatch: 0, anomaly: 0 },
      category_table: [],
      scenario_matrix: [
        { scenario_pct: '-0.10', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '-0.05', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '0.00', avg_margin_pct: null, profitable_count: 0 },
        { scenario_pct: '0.05', avg_margin_pct: null, profitable_count: 0 },
      ],
    })
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('Brak danych do policzenia')).toBeInTheDocument()
  })

  it('shows the API error message when the summary request fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'getReportSummary').mockRejectedValue(new ApiError('scan not found', 404))
    render(<ReportStep scanId="scan-1" />)

    expect(await screen.findByText('scan not found')).toBeInTheDocument()
  })
})
