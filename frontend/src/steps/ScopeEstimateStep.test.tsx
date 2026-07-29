import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeEstimateStep } from './ScopeEstimateStep'
import * as client from '../api/client'

const FILE = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })

const CREATE_RESULT = {
  scan_id: 'scan-1',
  status: 'estimated' as const,
  scope_type: 'full' as const,
  total_products: 10,
  completed_products: 0,
  estimate: {
    queries_without_refresh: 8,
    queries_with_refresh: 10,
    cost_usd_without_refresh: '0.08',
    cost_usd_with_refresh: '0.10',
    seconds_without_refresh: 4.0,
    seconds_with_refresh: 5.0,
  },
  overlapping_count: 2,
  stale_count: 1,
  warnings: ['Row 5: invalid EAN checksum \'123\', ean cleared'],
}

beforeEach(() => {
  vi.restoreAllMocks()
})
afterEach(() => {
  vi.restoreAllMocks()
})

describe('ScopeEstimateStep', () => {
  it('creates a scan with full scope by default and shows the estimate', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))
    expect(createScanSpy).toHaveBeenCalledWith(FILE, {
      scopeType: 'full',
      samplePerCategory: undefined,
      market: 'PL',
      maxDeliveryDays: 5,
      maxConcurrency: 5,
      stalenessThresholdDays: 14,
    })
    expect(await screen.findByText('0.08 USD')).toBeInTheDocument()
    expect(screen.getByText(/2 produkty.*nakładają się/i)).toBeInTheDocument()
    expect(screen.getByText(/1 z nich nie sprawdzano/i)).toBeInTheDocument()
    expect(screen.getByText(/invalid EAN checksum/)).toBeInTheDocument()
  })

  it('sends sample_per_category when the sample scope is chosen', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} />)

    await userEvent.click(screen.getByLabelText('Próbka per kategoria'))
    await userEvent.clear(screen.getByLabelText(/liczba produktów per kategoria/i))
    await userEvent.type(screen.getByLabelText(/liczba produktów per kategoria/i), '25')
    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() =>
      expect(createScanSpy).toHaveBeenCalledWith(
        FILE,
        expect.objectContaining({ scopeType: 'sample', samplePerCategory: 25 }),
      ),
    )
  })

  it('starts the scan with the chosen refresh decision and calls onStarted', async () => {
    vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    const startScanSpy = vi.spyOn(client, 'startScan').mockResolvedValue(undefined)
    const onStarted = vi.fn()
    render(<ScopeEstimateStep file={FILE} onStarted={onStarted} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await screen.findByText('0.08 USD')
    await userEvent.click(screen.getByLabelText(/odśwież nieświeże/i))
    await userEvent.click(screen.getByRole('button', { name: 'Uruchom skan' }))

    await waitFor(() => expect(startScanSpy).toHaveBeenCalledWith('scan-1', true))
    expect(onStarted).toHaveBeenCalledWith('scan-1')
  })

  it('shows the API error message when creating the scan fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'createScan').mockRejectedValue(
      new ApiError('max_concurrency must be >= 1, got 0', 400),
    )
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    expect(await screen.findByText('max_concurrency must be >= 1, got 0')).toBeInTheDocument()
  })
})
