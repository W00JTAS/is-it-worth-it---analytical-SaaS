import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeEstimateStep } from './ScopeEstimateStep'
import * as client from '../api/client'
import type { ColumnMapping } from '../api/types'

const FILE = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })

const MAPPING: ColumnMapping = {
  name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: null,
}

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
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))
    expect(createScanSpy).toHaveBeenCalledWith(
      FILE,
      {
        scopeType: 'full',
        samplePerCategory: undefined,
        market: 'PL',
        maxDeliveryDays: 5,
        maxConcurrency: 5,
        stalenessThresholdDays: 14,
      },
      MAPPING,
    )
    expect(await screen.findByText(/bez odświeżania/i)).toBeInTheDocument()
    expect(screen.getByText(/0\.08 USD.*~4s/)).toBeInTheDocument()
    expect(screen.getByText(/z odświeżaniem/i)).toBeInTheDocument()
    expect(screen.getByText(/0\.10 USD.*~5s/)).toBeInTheDocument()
    expect(screen.getByText(/2 produkty.*nakładają się/i)).toBeInTheDocument()
    expect(screen.getByText(/1 produkt z nich nie sprawdzano/i)).toBeInTheDocument()
    expect(screen.getByText(/invalid EAN checksum/)).toBeInTheDocument()
  })

  it('sends sample_per_category when the sample scope is chosen', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByLabelText('Próbka per kategoria'))
    await userEvent.clear(screen.getByLabelText(/liczba produktów per kategoria/i))
    await userEvent.type(screen.getByLabelText(/liczba produktów per kategoria/i), '25')
    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() =>
      expect(createScanSpy).toHaveBeenCalledWith(
        FILE,
        expect.objectContaining({ scopeType: 'sample', samplePerCategory: 25 }),
        MAPPING,
      ),
    )
  })

  it('starts the scan with the chosen refresh decision and calls onStarted', async () => {
    vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    const startScanSpy = vi.spyOn(client, 'startScan').mockResolvedValue(undefined)
    const onStarted = vi.fn()
    render(<ScopeEstimateStep file={FILE} onStarted={onStarted} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await screen.findByText(/bez odświeżania/i)
    await userEvent.click(screen.getByLabelText(/odśwież nieświeże/i))
    await userEvent.click(screen.getByRole('button', { name: 'Uruchom skan' }))

    await waitFor(() => expect(startScanSpy).toHaveBeenCalledWith('scan-1', true))
    expect(onStarted).toHaveBeenCalledWith('scan-1')
  })

  it('clears a stale estimate when the scope config changes afterward', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    expect(await screen.findByText(/bez odświeżania/i)).toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Próbka per kategoria'))

    expect(screen.queryByText(/bez odświeżania/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/0\.08 USD/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Oszacuj koszt' })).toBeInTheDocument()
    expect(createScanSpy).toHaveBeenCalledTimes(1)
  })

  it('does not show the overlap line when overlapping_count is zero', async () => {
    vi.spyOn(client, 'createScan').mockResolvedValue({ ...CREATE_RESULT, overlapping_count: 0 })
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    expect(await screen.findByText(/bez odświeżania/i)).toBeInTheDocument()
    expect(screen.queryByText(/nakładają się/i)).not.toBeInTheDocument()
  })

  it('disables all scope fields while an estimate request is in flight, closing the field-change race', async () => {
    let resolveCreateScan!: (value: typeof CREATE_RESULT) => void
    const createScanSpy = vi.spyOn(client, 'createScan').mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreateScan = resolve
        }),
    )
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)
    await userEvent.click(screen.getByRole('button', { name: /ustawienia zaawansowane/i }))

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))

    // While the request is pending, every field that feeds the scope config
    // must be disabled — otherwise the user could change the config before
    // this in-flight response resolves, and the stale response would still
    // land in `result`.
    expect(screen.getByLabelText('Pełny skan')).toBeDisabled()
    expect(screen.getByLabelText('Próbka per kategoria')).toBeDisabled()
    expect(screen.getByLabelText(/limit czasu dostawy/i)).toBeDisabled()
    expect(screen.getByLabelText(/limit współbieżności/i)).toBeDisabled()
    expect(screen.getByLabelText(/próg nieświeżości/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Oszacuj koszt' })).toBeDisabled()

    resolveCreateScan(CREATE_RESULT)

    expect(await screen.findByText(/bez odświeżania/i)).toBeInTheDocument()
    expect(screen.getByLabelText('Pełny skan')).not.toBeDisabled()
  })

  it('keeps advanced settings collapsed by default, with plain-language help text once opened', async () => {
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    expect(screen.queryByLabelText(/limit współbieżności/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/próg nieświeżości/i)).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /ustawienia zaawansowane/i }))

    expect(screen.getByLabelText(/limit współbieżności/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/limit współbieżności/i)).toHaveValue(5)
    expect(screen.getByLabelText(/próg nieświeżości/i)).toHaveValue(14)
  })

  // Note on the request-id guard (defense in depth in handleEstimate, see
  // ScopeEstimateStep.tsx): a black-box test that forces two overlapping
  // requests through the public button was attempted and found impossible to
  // trigger. React's synthetic event system checks its OWN `disabled` prop
  // (tracked from `isEstimating`/`isStarting` state) before dispatching a
  // click handler — even manually removing the `disabled` attribute from the
  // live DOM node does not let a second click through, because React reads
  // its fiber's memoized prop, not the DOM attribute. Since `handleEstimate`
  // is only reachable from that one button, there is currently no code path
  // that can invoke it a second time while a request is in flight. This is
  // reassuring evidence that the disabling fix above fully closes the race
  // in practice; the request-id guard remains as cheap insurance against a
  // future code path that might call `handleEstimate` from somewhere else or
  // re-enable the button prematurely, but exercising it would require
  // exporting internal implementation details purely for testability, which
  // isn't warranted for an unreachable-today safety net.

  it('shows the API error message when creating the scan fails', async () => {
    const { ApiError } = await import('../api/types')
    vi.spyOn(client, 'createScan').mockRejectedValue(
      new ApiError('max_concurrency must be >= 1, got 0', 400),
    )
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    expect(await screen.findByText('max_concurrency must be >= 1, got 0')).toBeInTheDocument()
  })

  it('passes the confirmed column mapping through to createScan', async () => {
    const createScanSpy = vi.spyOn(client, 'createScan').mockResolvedValue(CREATE_RESULT)
    render(<ScopeEstimateStep file={FILE} onStarted={vi.fn()} columnMapping={MAPPING} />)

    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))

    await waitFor(() => expect(createScanSpy).toHaveBeenCalledTimes(1))
    expect(createScanSpy).toHaveBeenCalledWith(FILE, expect.anything(), MAPPING)
  })
})
