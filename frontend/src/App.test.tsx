import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import * as client from './api/client'
import * as useScanEventsModule from './api/useScanEvents'

describe('App (ScanWizard)', () => {
  it('walks from upload through scope+estimate to progress', async () => {
    vi.spyOn(client, 'createScan').mockResolvedValue({
      scan_id: 'scan-1', status: 'estimated', scope_type: 'full',
      total_products: 5, completed_products: 0,
      estimate: {
        queries_without_refresh: 5, queries_with_refresh: 5,
        cost_usd_without_refresh: '0.05', cost_usd_with_refresh: '0.05',
        seconds_without_refresh: 2, seconds_with_refresh: 2,
      },
      overlapping_count: 0, stale_count: 0, warnings: [],
    })
    vi.spyOn(client, 'startScan').mockResolvedValue(undefined)
    vi.spyOn(useScanEventsModule, 'useScanEvents').mockReturnValue({
      scan: {
        scan_id: 'scan-1', status: 'running', scope_type: 'full',
        total_products: 5, completed_products: 2,
        estimate: {
          queries_without_refresh: 5, queries_with_refresh: 5,
          cost_usd_without_refresh: '0.05', cost_usd_with_refresh: '0.05',
          seconds_without_refresh: 2, seconds_with_refresh: 2,
        },
        overlapping_count: 0, stale_count: 0,
      },
      source: 'sse',
      error: null,
    })

    render(<App />)

    const file = new File(['nazwa;cena'], 'catalog.csv', { type: 'text/csv' })
    await userEvent.upload(screen.getByLabelText(/plik CSV/i), file)
    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))

    await screen.findByRole('heading', { name: 'Zakres skanu' })
    await userEvent.click(screen.getByRole('button', { name: 'Oszacuj koszt' }))
    await screen.findByText(/bez odświeżania/i)
    await userEvent.click(screen.getByRole('button', { name: 'Uruchom skan' }))

    await screen.findByRole('heading', { name: 'Przebieg skanu' })
    expect(screen.getByText('2 / 5')).toBeInTheDocument()
  })
})
