import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useScanEvents } from './useScanEvents'
import * as client from './client'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  closed = false
  url: string

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }

  emitMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }

  emitError() {
    this.onerror?.(new Event('error'))
  }
}

function scanPayload(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    scan_id: 'scan-1',
    status: 'running',
    scope_type: 'full',
    total_products: 10,
    completed_products: 3,
    estimate: {
      queries_without_refresh: 8, queries_with_refresh: 10,
      cost_usd_without_refresh: '0.08', cost_usd_with_refresh: '0.10',
      seconds_without_refresh: 4.0, seconds_with_refresh: 5.0,
    },
    overlapping_count: 2,
    stale_count: 2,
    ...overrides,
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.useFakeTimers()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('useScanEvents', () => {
  it('connects to the scan-specific events URL', () => {
    renderHook(() => useScanEvents('scan-1'))

    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0].url).toBe('/scans/scan-1/events')
  })

  it('does not connect when scanId is null', () => {
    renderHook(() => useScanEvents(null))

    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('updates scan state from incoming messages', () => {
    const { result } = renderHook(() => useScanEvents('scan-1'))

    FakeEventSource.instances[0].emitMessage(scanPayload({ completed_products: 5 }))

    expect(result.current.scan?.completed_products).toBe(5)
    expect(result.current.source).toBe('sse')
    expect(result.current.error).toBeNull()
  })

  it('closes the connection on a terminal status', () => {
    renderHook(() => useScanEvents('scan-1'))

    FakeEventSource.instances[0].emitMessage(scanPayload({ status: 'done' }))

    expect(FakeEventSource.instances[0].closed).toBe(true)
  })

  it('surfaces a timeout payload as an error and closes the connection', () => {
    const { result } = renderHook(() => useScanEvents('scan-1'))

    FakeEventSource.instances[0].emitMessage({
      scan_id: 'scan-1', status: 'timeout', detail: 'scan was never started',
    })

    expect(result.current.error).toBe('scan was never started')
    expect(FakeEventSource.instances[0].closed).toBe(true)
  })

  it('reconnects on error up to 3 times before falling back to polling', async () => {
    const getScanSpy = vi.spyOn(client, 'getScan').mockResolvedValue(scanPayload() as never)
    renderHook(() => useScanEvents('scan-1'))

    // 3 reconnect attempts: each error closes the current source and, after a
    // backoff, opens a new one.
    for (let attempt = 1; attempt <= 3; attempt++) {
      const current = FakeEventSource.instances[FakeEventSource.instances.length - 1]
      current.emitError()
      await vi.advanceTimersByTimeAsync(500 * attempt)
    }
    expect(FakeEventSource.instances).toHaveLength(4) // initial + 3 reconnects

    // A 4th error exceeds the retry budget -> falls back to polling, no 5th EventSource.
    const last = FakeEventSource.instances[FakeEventSource.instances.length - 1]
    last.emitError()
    await vi.advanceTimersByTimeAsync(0)

    expect(FakeEventSource.instances).toHaveLength(4)
    expect(getScanSpy).not.toHaveBeenCalled() // polling hasn't ticked yet

    await vi.advanceTimersByTimeAsync(2000)
    expect(getScanSpy).toHaveBeenCalledWith('scan-1')
  })

  it('reports source "polling" once it falls back', async () => {
    vi.spyOn(client, 'getScan').mockResolvedValue(scanPayload({ completed_products: 7 }) as never)
    const { result } = renderHook(() => useScanEvents('scan-1'))

    for (let attempt = 1; attempt <= 4; attempt++) {
      const current = FakeEventSource.instances[FakeEventSource.instances.length - 1]
      current.emitError()
      await vi.advanceTimersByTimeAsync(500 * attempt)
    }

    await vi.advanceTimersByTimeAsync(2000)
    expect(result.current.source).toBe('polling')
    expect(result.current.scan?.completed_products).toBe(7)
  })

  it('stops polling once a terminal status is reached', async () => {
    const getScanSpy = vi
      .spyOn(client, 'getScan')
      .mockResolvedValue(scanPayload({ status: 'done' }) as never)
    const { result } = renderHook(() => useScanEvents('scan-1'))

    for (let attempt = 1; attempt <= 4; attempt++) {
      const current = FakeEventSource.instances[FakeEventSource.instances.length - 1]
      current.emitError()
      await vi.advanceTimersByTimeAsync(500 * attempt)
    }
    await vi.advanceTimersByTimeAsync(2000)
    expect(result.current.scan?.status).toBe('done')

    const callsAtDone = getScanSpy.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(getScanSpy.mock.calls.length).toBe(callsAtDone) // no further polling ticks
  })
})
