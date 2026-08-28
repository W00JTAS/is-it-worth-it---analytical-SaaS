import { useEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { getScan } from './client'
import type { Scan } from './types'

export type ScanEventsSource = 'sse' | 'polling'

export interface ScanEventsState {
  scan: Scan | null
  source: ScanEventsSource
  error: string | null
}

const MAX_RECONNECT_ATTEMPTS = 3
const POLL_INTERVAL_MS = 2000

function isTerminal(status: string): boolean {
  return status === 'done' || status === 'failed' || status === 'paused'
}

export function useScanEvents(scanId: string | null): ScanEventsState {
  const [scan, setScan] = useState<Scan | null>(null)
  const [source, setSource] = useState<ScanEventsSource>('sse')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!scanId) return

    let cancelled = false
    let reconnectAttempts = 0
    let eventSource: EventSource | null = null
    let pollTimer: ReturnType<typeof setInterval> | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    function startPolling() {
      if (cancelled) return
      flushSync(() => setSource('polling'))
      const poll = async () => {
        try {
          // safe: the effect returns early above when scanId is null
          const result = await getScan(scanId as string)
          if (cancelled) return
          flushSync(() => {
            setScan(result)
            setError(null)
          })
          if (isTerminal(result.status) && pollTimer) {
            clearInterval(pollTimer)
            pollTimer = null
          }
        } catch {
          if (!cancelled) flushSync(() => setError('Nie udało się pobrać statusu skanu'))
        }
      }
      // Rely solely on the interval tick for the first (and every subsequent)
      // poll — no immediate call here. Calling `poll()` eagerly would fire
      // `getScan` synchronously the moment we fall back, before the caller
      // has had a chance to observe the pre-poll state.
      pollTimer = setInterval(poll, POLL_INTERVAL_MS)
    }

    function connect() {
      if (cancelled) return
      eventSource = new EventSource(`/scans/${scanId}/events`)

      eventSource.onmessage = (event) => {
        if (cancelled) return
        reconnectAttempts = 0
        const data = JSON.parse(event.data)
        if (data.status === 'timeout') {
          flushSync(() => setError(data.detail ?? 'Skan nigdy nie został uruchomiony'))
          eventSource?.close()
          return
        }
        flushSync(() => {
          setScan(data)
          setError(null)
        })
        if (isTerminal(data.status)) {
          eventSource?.close()
        }
      }

      eventSource.onerror = () => {
        if (cancelled) return
        eventSource?.close()
        reconnectAttempts += 1
        if (reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
          startPolling()
        } else {
          reconnectTimer = setTimeout(connect, 500 * reconnectAttempts)
        }
      }
    }

    connect()

    return () => {
      cancelled = true
      eventSource?.close()
      if (pollTimer) clearInterval(pollTimer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [scanId])

  return { scan, source, error }
}
