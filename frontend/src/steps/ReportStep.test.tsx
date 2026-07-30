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

const PRODUCT_PAGE = {
  total: 2,
  page: 1,
  page_size: 25,
  rows: [
    {
      id: 1, external_id: 'p1', name: 'Zebra Gadget', category: 'Elektronika', ean: '123',
      wholesale_price: '40.00', currency: 'PLN', computable: true,
      exclusion_reason: null, anomaly_flag: null,
      offer: {
        price: '100.00', currency: 'PLN', seller: 'Shop', source_url: 'https://example.com/x',
        delivery_days: 2, confidence: 0.9, citations: [],
      },
      margin_matrix: [
        { scenario_pct: '-0.10', sale_price: '90.00', net_revenue: '73.17', total_costs: '64.80', margin: '8.37', margin_pct: '0.0930' },
        { scenario_pct: '-0.05', sale_price: '95.00', net_revenue: '77.24', total_costs: '68.30', margin: '8.94', margin_pct: '0.0941' },
        { scenario_pct: '0.00', sale_price: '100.00', net_revenue: '81.30', total_costs: '54.00', margin: '27.30', margin_pct: '0.2730' },
        { scenario_pct: '0.05', sale_price: '105.00', net_revenue: '85.37', total_costs: '75.30', margin: '10.07', margin_pct: '0.0959' },
      ],
    },
    {
      id: 2, external_id: 'p2', name: 'Apple Widget', category: 'Elektronika', ean: null,
      wholesale_price: '30.00', currency: 'PLN', computable: false,
      exclusion_reason: 'no_offer', anomaly_flag: null,
      offer: null, margin_matrix: null,
    },
  ],
}

describe('ReportStep product drill-down', () => {
  it('loads and renders the product page after the summary loads', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)

    await screen.findByText('Zebra Gadget')
    expect(screen.getByText('Apple Widget')).toBeInTheDocument()
    expect(productsSpy).toHaveBeenCalledWith(
      'scan-1',
      { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
      { category: undefined, status: undefined, sort: 'category', page: 1, pageSize: 25 },
    )
  })

  it('expands a row to show offer details and the full margin matrix', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.click(screen.getByText('Zebra Gadget'))

    expect(await screen.findByText('Shop')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/x')).toBeInTheDocument()
  })

  it('reloads page 1 when the status filter changes', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue(PRODUCT_PAGE)
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.selectOptions(screen.getByLabelText('Status'), 'no_offer')

    await waitFor(() =>
      expect(productsSpy).toHaveBeenLastCalledWith(
        'scan-1',
        { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
        { category: undefined, status: 'no_offer', sort: 'category', page: 1, pageSize: 25 },
      ),
    )
  })

  it('requests the next page when Następna is clicked', async () => {
    vi.spyOn(client, 'getReportSummary').mockResolvedValue(SUMMARY)
    const productsSpy = vi.spyOn(client, 'getReportProducts').mockResolvedValue({
      ...PRODUCT_PAGE, total: 30,
    })
    render(<ReportStep scanId="scan-1" />)
    await screen.findByText('Zebra Gadget')

    await userEvent.click(screen.getByRole('button', { name: 'Następna' }))

    await waitFor(() =>
      expect(productsSpy).toHaveBeenLastCalledWith(
        'scan-1',
        { commissionPct: '0.15', shippingCost: '0.00', vatPct: '0.23', returnsPct: '0.05' },
        { category: undefined, status: undefined, sort: 'category', page: 2, pageSize: 25 },
      ),
    )
  })
})
