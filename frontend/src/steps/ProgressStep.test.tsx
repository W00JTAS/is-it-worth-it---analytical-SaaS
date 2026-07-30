// frontend/src/steps/ProgressStep.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ProgressStep } from './ProgressStep'
import * as useScanEventsModule from '../api/useScanEvents'

function mockScanEvents(overrides: Partial<useScanEventsModule.ScanEventsState> = {}) {
  vi.spyOn(useScanEventsModule, 'useScanEvents').mockReturnValue({
    scan: null,
    source: 'sse',
    error: null,
    ...overrides,
  })
}

describe('ProgressStep', () => {
  it('shows a progress count while running', () => {
    mockScanEvents({
      scan: {
        scan_id: 'scan-1', status: 'running', scope_type: 'full',
        total_products: 20, completed_products: 7,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)

    expect(screen.getByText('7 / 20')).toBeInTheDocument()
  })

  it('shows a completion summary when status is done', () => {
    mockScanEvents({
      scan: {
        scan_id: 'scan-1', status: 'done', scope_type: 'full',
        total_products: 20, completed_products: 20,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)

    expect(screen.getByText(/skan zakończony/i)).toBeInTheDocument()
    expect(screen.getByText('20 / 20')).toBeInTheDocument()
  })

  it('shows a distinct, non-success treatment when status is failed', () => {
    mockScanEvents({
      scan: {
        scan_id: 'scan-1', status: 'failed', scope_type: 'full',
        total_products: 20, completed_products: 12,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)

    const failedMessage = screen.getByText(/skan zakończony z błędami/i)
    expect(failedMessage).toBeInTheDocument()
    expect(failedMessage.className).toContain('text-red-400')
    expect(failedMessage.className).not.toContain('text-emerald-400')
  })

  it('shows a polling indicator when the source falls back to polling', () => {
    mockScanEvents({
      source: 'polling',
      scan: {
        scan_id: 'scan-1', status: 'running', scope_type: 'full',
        total_products: 20, completed_products: 7,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)

    expect(screen.getByText(/aktualizacja co kilka sekund/i)).toBeInTheDocument()
  })

  it('shows an error message when the hook reports one', () => {
    mockScanEvents({ error: 'scan was never started' })

    render(<ProgressStep scanId="scan-1" onDone={vi.fn()} />)

    expect(screen.getByText('scan was never started')).toBeInTheDocument()
  })

  it('calls onDone with the scan id when Zobacz raport is clicked, once the scan is done', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    const onDone = vi.fn()
    mockScanEvents({
      scan: {
        scan_id: 'scan-1', status: 'done', scope_type: 'full',
        total_products: 20, completed_products: 20,
        estimate: {
          queries_without_refresh: 20, queries_with_refresh: 20,
          cost_usd_without_refresh: '0.20', cost_usd_with_refresh: '0.20',
          seconds_without_refresh: 10, seconds_with_refresh: 10,
        },
        overlapping_count: 0, stale_count: 0,
      },
    })

    render(<ProgressStep scanId="scan-1" onDone={onDone} />)
    await userEvent.click(screen.getByRole('button', { name: 'Zobacz raport' }))

    expect(onDone).toHaveBeenCalledWith('scan-1')
  })
})
