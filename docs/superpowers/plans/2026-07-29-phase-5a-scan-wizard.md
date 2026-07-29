# Phase 5a — Scan Wizard Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three-screen wizard (Upload → Scope+Estimate → Progress) that lets a
user upload a CSV catalog, choose a scan scope, see a cost/time estimate before spending
anything, start the scan, and watch live progress to completion — consuming Phase 4's
existing REST+SSE API with zero new backend work.

**Architecture:** A single top-level `ScanWizard` component holds which step is active and
the data handed between steps (the selected `File` → the created scan's id and estimate →
live progress). Three focused step components, each with one job. A small `api/` module
(types + `fetch`-based client functions) and a `useScanEvents` hook (SSE with automatic
reconnect, falling back to polling) are the only shared infrastructure.

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind v4 (already scaffolded). Vitest +
React Testing Library added in Task 1 for TDD, matching the backend's existing rigor — this
is the frontend's first test infrastructure. No new production dependencies beyond what's
already in `package.json`.

## Global Constraints

- No new runtime dependencies beyond `vitest`/`@testing-library/*`/`jsdom` (all dev-only,
  approved for testing infrastructure) — no router library, no data-fetching library
  (TanStack Query etc.), no SSE polyfill library.
- No routing library: a single page, step held in component state.
- Zero real network calls in any test — `fetch` and `EventSource` are mocked/faked.
- The three-step flow is: Upload (pick a file) → Scope+Estimate (choose scan parameters,
  call `POST /scans` which spends nothing, review the estimate, decide on refreshing stale
  products, call `POST /scans/{id}/start`) → Progress (live updates via SSE, falling back to
  polling on connection failure, terminal summary on `done`/`failed`).
- Out of scope for this plan (per the design spec, deferred to later sub-phases): the
  column-mapping correction screen, the Report screen, live running-cost display during a
  scan (the API only exposes product counts, not cost-so-far).
- Visual direction: dark theme (`slate-950` background, `slate-100` text — already the
  scaffold's choice in `src/App.tsx`), a single `emerald` accent color for primary actions
  and progress indication. Every task's UI code in this plan already reflects this — don't
  introduce a different palette.
- Vite dev server needs to reach the FastAPI backend (`localhost:8000` in local dev) without
  CORS: Task 1 adds a Vite dev-server proxy for the API paths, so the frontend code calls
  relative URLs (`/scans`, `/scans/{id}`, `/scans/{id}/events`) and the proxy forwards them —
  no CORS middleware needed on the backend, no absolute URLs in the frontend.

---

## File Structure

- Modify: `frontend/package.json` — add `vitest`, `@testing-library/react`,
  `@testing-library/jest-dom`, `@testing-library/user-event`, `jsdom` as devDependencies;
  add a `test` script.
- Modify: `frontend/vite.config.ts` — switch to `vitest/config`'s `defineConfig` (a superset
  of Vite's own), add the `test` block and the dev-server proxy.
- Create: `frontend/src/test/setup.ts` — Vitest setup file (jest-dom matchers).
- Create: `frontend/src/App.test.tsx` — the harness-proving smoke test (Task 1 only; later
  tasks replace `App.tsx`'s content, and a later task updates this test to match).
- Create: `frontend/src/api/types.ts` — TypeScript types mirroring the backend's JSON shapes
  exactly, plus `ApiError`.
- Create: `frontend/src/api/client.ts` — `createScan`, `startScan`, `getScan`.
- Test: `frontend/src/api/client.test.ts`
- Create: `frontend/src/api/useScanEvents.ts` — the SSE-with-reconnect-and-polling-fallback
  hook.
- Test: `frontend/src/api/useScanEvents.test.ts`
- Create: `frontend/src/steps/UploadStep.tsx`
- Test: `frontend/src/steps/UploadStep.test.tsx`
- Create: `frontend/src/steps/ScopeEstimateStep.tsx`
- Test: `frontend/src/steps/ScopeEstimateStep.test.tsx`
- Create: `frontend/src/steps/ProgressStep.tsx`
- Test: `frontend/src/steps/ProgressStep.test.tsx`
- Modify: `frontend/src/App.tsx` — becomes `ScanWizard`'s host (replaces the placeholder).
- Test: `frontend/src/App.test.tsx` — updated in the final task to test the wired-up wizard.

---

## Task 1: Test infrastructure (Vitest + React Testing Library) + dev proxy

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: a working `npm test` command (`vitest run`), a jsdom test environment with
  jest-dom matchers globally available, and a Vite dev-server proxy forwarding `/scans` and
  `/health` to `http://localhost:8000`. Every later task's tests depend on this harness
  existing and working.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/App.test.tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders the scaffold placeholder', () => {
    render(<App />)
    expect(screen.getByText('IS_IT_WORTH_IT — scaffold ready')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `vitest` is not installed yet (`command not found` or `npm error`).

- [ ] **Step 3: Install the test dependencies**

Run:
```bash
cd frontend
npm install -D vitest@4.1.10 @testing-library/react@16.3.2 @testing-library/jest-dom@7.0.0 @testing-library/user-event@14.6.1 jsdom@30.0.1
```

- [ ] **Step 4: Configure Vitest, jsdom setup, and the dev proxy**

```ts
// frontend/vite.config.ts
/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/scans': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
```

```ts
// frontend/src/test/setup.ts
import '@testing-library/jest-dom/vitest'
```

Add to `frontend/package.json`'s `"scripts"` section (alongside the existing `dev`/`build`/`lint`/`preview`):

```json
"test": "vitest run"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (1 test)

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/src/test/setup.ts frontend/src/App.test.tsx
git commit -m "Add Vitest + React Testing Library test infrastructure and dev API proxy"
```

---

## Task 2: API types and client functions

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces:
  - Types: `ScanStatus` (`"estimated" | "running" | "done" | "failed"`), `ScopeType`
    (`"full" | "sample"`), `CostEstimate`, `Scan`, `CreateScanResult` (`Scan &
    { warnings: string[] }`), `ScopeConfig`, `ApiError` (an `Error` subclass with a `status:
    number` field).
  - Functions: `createScan(file: File, scope: ScopeConfig): Promise<CreateScanResult>`,
    `startScan(scanId: string, forceRefreshStale: boolean): Promise<void>`,
    `getScan(scanId: string): Promise<Scan>`.
  All three functions throw `ApiError` on a non-2xx response. Used by Task 3's
  `useScanEvents` (`getScan`) and Tasks 4-5's step components (`createScan`, `startScan`).

The exact JSON shapes below match `backend/app/scans/api.py`'s `_scan_to_dict` /
`_estimate_to_dict` / the `POST /scans` response exactly — do not rename any field.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/client.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './types'
import { createScan, getScan, startScan } from './client'
import type { ScopeConfig } from './types'

const SCAN_JSON = {
  scan_id: 'scan-1',
  status: 'estimated',
  scope_type: 'full',
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
  stale_count: 2,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const FULL_SCOPE: ScopeConfig = {
  scopeType: 'full',
  market: 'PL',
  maxDeliveryDays: 5,
  maxConcurrency: 5,
  stalenessThresholdDays: 14,
}

describe('createScan', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts multipart form data with the file and scope fields', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...SCAN_JSON, warnings: [] }))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })

    const result = await createScan(file, FULL_SCOPE)

    expect(result.scan_id).toBe('scan-1')
    expect(result.warnings).toEqual([])
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/scans')
    expect(init?.method).toBe('POST')
    const body = init?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
    expect(body.get('scope_type')).toBe('full')
    expect(body.get('market')).toBe('PL')
    expect(body.get('max_delivery_days')).toBe('5')
    expect(body.get('max_concurrency')).toBe('5')
    expect(body.get('staleness_threshold_days')).toBe('14')
  })

  it('includes sample_per_category only when the scope is a sample', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ ...SCAN_JSON, warnings: [] }))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })

    await createScan(file, { ...FULL_SCOPE, scopeType: 'sample', samplePerCategory: 50 })

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = init?.body as FormData
    expect(body.get('scope_type')).toBe('sample')
    expect(body.get('sample_per_category')).toBe('50')
  })

  it('throws ApiError with the backend detail message on a 400', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: 'max_concurrency must be >= 1, got 0' }, 400),
    )
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })

    await expect(createScan(file, FULL_SCOPE)).rejects.toMatchObject({
      message: 'max_concurrency must be >= 1, got 0',
      status: 400,
    })
    await expect(createScan(file, FULL_SCOPE)).rejects.toBeInstanceOf(ApiError)
  })
})

describe('startScan', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts force_refresh_stale as JSON to the scan-specific start endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ status: 'running' }))

    await startScan('scan-1', true)

    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/scans/scan-1/start')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({ force_refresh_stale: true })
  })

  it('throws ApiError with status 409 when the scan is already running', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'scan already running' }, 409))

    await expect(startScan('scan-1', false)).rejects.toMatchObject({ status: 409 })
  })
})

describe('getScan', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fetches the scan by id', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SCAN_JSON))

    const result = await getScan('scan-1')

    expect(result).toEqual(SCAN_JSON)
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/scans/scan-1')
  })

  it('throws ApiError with status 404 for an unknown scan', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'scan not found' }, 404))

    await expect(getScan('missing')).rejects.toMatchObject({ status: 404 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './types'` / `./client`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/api/types.ts
export type ScanStatus = 'estimated' | 'running' | 'done' | 'failed'
export type ScopeType = 'full' | 'sample'

export interface CostEstimate {
  queries_without_refresh: number
  queries_with_refresh: number
  cost_usd_without_refresh: string
  cost_usd_with_refresh: string
  seconds_without_refresh: number
  seconds_with_refresh: number
}

export interface Scan {
  scan_id: string
  status: ScanStatus
  scope_type: ScopeType
  total_products: number
  completed_products: number
  estimate: CostEstimate
  overlapping_count: number
  stale_count: number
}

export interface CreateScanResult extends Scan {
  warnings: string[]
}

export interface ScopeConfig {
  scopeType: ScopeType
  samplePerCategory?: number
  market: string
  maxDeliveryDays: number
  maxConcurrency: number
  stalenessThresholdDays: number
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
```

```ts
// frontend/src/api/client.ts
import { ApiError } from './types'
import type { CreateScanResult, Scan, ScopeConfig } from './types'

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // Response body wasn't JSON (or was empty) — fall through to a generic message.
  }
  return `Request failed with status ${response.status}`
}

export async function createScan(file: File, scope: ScopeConfig): Promise<CreateScanResult> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('scope_type', scope.scopeType)
  if (scope.samplePerCategory !== undefined) {
    formData.append('sample_per_category', String(scope.samplePerCategory))
  }
  formData.append('market', scope.market)
  formData.append('max_delivery_days', String(scope.maxDeliveryDays))
  formData.append('max_concurrency', String(scope.maxConcurrency))
  formData.append('staleness_threshold_days', String(scope.stalenessThresholdDays))

  const response = await fetch('/scans', { method: 'POST', body: formData })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}

export async function startScan(scanId: string, forceRefreshStale: boolean): Promise<void> {
  const response = await fetch(`/scans/${scanId}/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force_refresh_stale: forceRefreshStale }),
  })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
}

export async function getScan(scanId: string): Promise<Scan> {
  const response = await fetch(`/scans/${scanId}`)
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts
git commit -m "Add API types and fetch-based client for scan endpoints"
```

---

## Task 3: `useScanEvents` — SSE with reconnect and polling fallback

**Files:**
- Create: `frontend/src/api/useScanEvents.ts`
- Test: `frontend/src/api/useScanEvents.test.ts`

**Interfaces:**
- Consumes: `getScan` from Task 2's `./client`, `Scan` from `./types`.
- Produces: `useScanEvents(scanId: string | null): { scan: Scan | null; source: 'sse' |
  'polling'; error: string | null }`. Used by Task 6's `ProgressStep`.

Behavior: opens `new EventSource(\`/scans/${scanId}/events\`)`. On each message, parses the
JSON and updates `scan` (matching `Scan`'s shape, per Task 3's `stream_scan_events` in
`backend/app/scans/api.py`, which emits the same shape as `GET /scans/{id}`), unless the
payload is the terminal `{"status": "timeout", ...}` event (sent when a scan is never
started — see `SSE_MAX_ESTIMATED_TICKS` in `api.py`), which is surfaced as `error` instead
and closes the connection. On `done`/`failed`, closes the connection (no more updates
expected). On a connection error, closes and retries with a short backoff up to 3 attempts;
after that, switches to polling `getScan` every 2 seconds until a terminal status, and
`source` becomes `'polling'` so the UI can show that live updates are less immediate.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/useScanEvents.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
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
    await waitFor(() => expect(getScanSpy).toHaveBeenCalledWith('scan-1'))
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
    await waitFor(() => expect(result.current.source).toBe('polling'))
    await waitFor(() => expect(result.current.scan?.completed_products).toBe(7))
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
    await waitFor(() => expect(result.current.scan?.status).toBe('done'))

    const callsAtDone = getScanSpy.mock.calls.length
    await vi.advanceTimersByTimeAsync(10000)
    expect(getScanSpy.mock.calls.length).toBe(callsAtDone) // no further polling ticks
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './useScanEvents'`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/api/useScanEvents.ts
import { useEffect, useState } from 'react'
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
  return status === 'done' || status === 'failed'
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
      setSource('polling')
      const poll = async () => {
        try {
          const result = await getScan(scanId)
          if (cancelled) return
          setScan(result)
          setError(null)
          if (isTerminal(result.status) && pollTimer) {
            clearInterval(pollTimer)
            pollTimer = null
          }
        } catch {
          if (!cancelled) setError('Nie udało się pobrać statusu skanu')
        }
      }
      poll()
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
          setError(data.detail ?? 'Skan nigdy nie został uruchomiony')
          eventSource?.close()
          return
        }
        setScan(data)
        setError(null)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/useScanEvents.ts frontend/src/api/useScanEvents.test.ts
git commit -m "Add useScanEvents hook: SSE with reconnect and polling fallback"
```

---

## Task 4: `UploadStep`

**Files:**
- Create: `frontend/src/steps/UploadStep.tsx`
- Test: `frontend/src/steps/UploadStep.test.tsx`

**Interfaces:**
- Produces: `UploadStep({ onFileSelected }: { onFileSelected: (file: File) => void })` — a
  file picker restricted to `.csv`, with a "Dalej" button disabled until a file is chosen,
  calling `onFileSelected` with the chosen `File` when clicked. No API call in this
  component — the file is just handed up to the wizard; `POST /scans` (which needs both the
  file and the scope config) happens in Task 5's `ScopeEstimateStep`. Used by Task 7's
  `ScanWizard`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/steps/UploadStep.test.tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UploadStep } from './UploadStep'

describe('UploadStep', () => {
  it('disables the next button until a file is chosen', async () => {
    render(<UploadStep onFileSelected={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeDisabled()

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/plik CSV/i)
    await userEvent.upload(input, file)

    expect(screen.getByRole('button', { name: 'Dalej' })).toBeEnabled()
  })

  it('calls onFileSelected with the chosen file when Dalej is clicked', async () => {
    const onFileSelected = vi.fn()
    render(<UploadStep onFileSelected={onFileSelected} />)

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/plik CSV/i)
    await userEvent.upload(input, file)
    await userEvent.click(screen.getByRole('button', { name: 'Dalej' }))

    expect(onFileSelected).toHaveBeenCalledWith(file)
  })

  it('shows the chosen file name', async () => {
    render(<UploadStep onFileSelected={vi.fn()} />)

    const file = new File(['nazwa;cena\nA;10,00'], 'catalog.csv', { type: 'text/csv' })
    const input = screen.getByLabelText(/plik CSV/i)
    await userEvent.upload(input, file)

    expect(screen.getByText('catalog.csv')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './UploadStep'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/steps/UploadStep.tsx
import { useState } from 'react'
import type { ChangeEvent } from 'react'

interface UploadStepProps {
  onFileSelected: (file: File) => void
}

export function UploadStep({ onFileSelected }: UploadStepProps) {
  const [file, setFile] = useState<File | null>(null)

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Wgraj katalog</h1>
      <label className="flex flex-col gap-2 text-sm text-slate-300" htmlFor="csv-upload">
        Plik CSV od hurtowni
        <input
          id="csv-upload"
          type="file"
          accept=".csv"
          onChange={handleChange}
          className="rounded-md border border-slate-700 bg-slate-900 p-2 text-slate-100 file:mr-3 file:rounded file:border-0 file:bg-emerald-600 file:px-3 file:py-1.5 file:text-slate-950 file:font-medium"
        />
      </label>
      {file && <p className="text-sm text-slate-400">{file.name}</p>}
      <button
        type="button"
        disabled={!file}
        onClick={() => file && onFileSelected(file)}
        className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        Dalej
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/steps/UploadStep.tsx frontend/src/steps/UploadStep.test.tsx
git commit -m "Add UploadStep component"
```

---

## Task 5: `ScopeEstimateStep`

**Files:**
- Create: `frontend/src/steps/ScopeEstimateStep.tsx`
- Test: `frontend/src/steps/ScopeEstimateStep.test.tsx`

**Interfaces:**
- Consumes: `createScan`, `startScan` from Task 2's `../api/client`; `CreateScanResult`,
  `ScopeConfig` from `../api/types`.
- Produces: `ScopeEstimateStep({ file, onStarted }: { file: File; onStarted: (scanId:
  string) => void })`. Internally two phases: a scope form that calls `createScan` on submit
  and shows the estimate/overlap/warnings, then a "force refresh stale?" choice and a
  "Start" button that calls `startScan` and, on success, calls `onStarted(scanId)`. Used by
  Task 7's `ScanWizard`.

Defaults match the backend's own defaults exactly (`backend/app/scans/api.py`'s `Form(...)`
defaults): `market="PL"`, `maxDeliveryDays=5`, `maxConcurrency=5`,
`stalenessThresholdDays=14`, `scopeType="full"`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/steps/ScopeEstimateStep.test.tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './ScopeEstimateStep'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/steps/ScopeEstimateStep.tsx
import { useState } from 'react'
import { createScan, startScan } from '../api/client'
import { ApiError } from '../api/types'
import type { CreateScanResult, ScopeType } from '../api/types'

interface ScopeEstimateStepProps {
  file: File
  onStarted: (scanId: string) => void
}

export function ScopeEstimateStep({ file, onStarted }: ScopeEstimateStepProps) {
  const [scopeType, setScopeType] = useState<ScopeType>('full')
  const [samplePerCategory, setSamplePerCategory] = useState('50')
  const [maxDeliveryDays, setMaxDeliveryDays] = useState(5)
  const [maxConcurrency, setMaxConcurrency] = useState(5)
  const [stalenessThresholdDays, setStalenessThresholdDays] = useState(14)
  const [result, setResult] = useState<CreateScanResult | null>(null)
  const [forceRefreshStale, setForceRefreshStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isEstimating, setIsEstimating] = useState(false)
  const [isStarting, setIsStarting] = useState(false)

  async function handleEstimate() {
    setError(null)
    setIsEstimating(true)
    try {
      const created = await createScan(file, {
        scopeType,
        samplePerCategory: scopeType === 'sample' ? Number(samplePerCategory) : undefined,
        market: 'PL',
        maxDeliveryDays,
        maxConcurrency,
        stalenessThresholdDays,
      })
      setResult(created)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się oszacować kosztu')
    } finally {
      setIsEstimating(false)
    }
  }

  async function handleStart() {
    if (!result) return
    setError(null)
    setIsStarting(true)
    try {
      await startScan(result.scan_id, forceRefreshStale)
      onStarted(result.scan_id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się uruchomić skanu')
    } finally {
      setIsStarting(false)
    }
  }

  const cost = forceRefreshStale
    ? result?.estimate.cost_usd_with_refresh
    : result?.estimate.cost_usd_without_refresh

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Zakres skanu</h1>

      <fieldset className="flex flex-col gap-2 text-sm text-slate-300">
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="scope"
            checked={scopeType === 'full'}
            onChange={() => setScopeType('full')}
          />
          Pełny skan
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="scope"
            checked={scopeType === 'sample'}
            onChange={() => setScopeType('sample')}
          />
          Próbka per kategoria
        </label>
        {scopeType === 'sample' && (
          <label className="flex flex-col gap-1 pl-6">
            Liczba produktów per kategoria
            <input
              type="number"
              min={1}
              value={samplePerCategory}
              onChange={(e) => setSamplePerCategory(e.target.value)}
              className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
            />
          </label>
        )}
      </fieldset>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Limit czasu dostawy (dni)
        <input
          type="number"
          min={1}
          value={maxDeliveryDays}
          onChange={(e) => setMaxDeliveryDays(Number(e.target.value))}
          className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Limit współbieżności
        <input
          type="number"
          min={1}
          value={maxConcurrency}
          onChange={(e) => setMaxConcurrency(Number(e.target.value))}
          className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Próg nieświeżości (dni)
        <input
          type="number"
          min={0}
          value={stalenessThresholdDays}
          onChange={(e) => setStalenessThresholdDays(Number(e.target.value))}
          className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
        />
      </label>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {!result && (
        <button
          type="button"
          onClick={handleEstimate}
          disabled={isEstimating}
          className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
        >
          Oszacuj koszt
        </button>
      )}

      {result && (
        <div className="flex flex-col gap-3 rounded-md border border-slate-700 p-4 text-sm text-slate-200">
          <p>
            Szacowany koszt: <span className="font-semibold">{cost} USD</span>
          </p>
          <p>{result.overlapping_count} produkty w tym skanie nakładają się z poprzednimi skanami.</p>
          {result.stale_count > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={forceRefreshStale}
                onChange={(e) => setForceRefreshStale(e.target.checked)}
              />
              Odśwież nieświeże ({result.stale_count} z nich nie sprawdzano od dawna)
            </label>
          )}
          {result.warnings.length > 0 && (
            <ul className="list-inside list-disc text-amber-400">
              {result.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={handleStart}
            disabled={isStarting}
            className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
          >
            Uruchom skan
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/steps/ScopeEstimateStep.tsx frontend/src/steps/ScopeEstimateStep.test.tsx
git commit -m "Add ScopeEstimateStep component"
```

---

## Task 6: `ProgressStep`

**Files:**
- Create: `frontend/src/steps/ProgressStep.tsx`
- Test: `frontend/src/steps/ProgressStep.test.tsx`

**Interfaces:**
- Consumes: `useScanEvents` from Task 3's `../api/useScanEvents`.
- Produces: `ProgressStep({ scanId }: { scanId: string })` — renders a progress bar
  (`completed_products` / `total_products`), a subtle indicator when `source === 'polling'`,
  and a terminal summary once `status` is `done` or `failed`. Used by Task 7's `ScanWizard`.

- [ ] **Step 1: Write the failing test**

```tsx
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

    render(<ProgressStep scanId="scan-1" />)

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

    render(<ProgressStep scanId="scan-1" />)

    expect(screen.getByText(/skan zakończony/i)).toBeInTheDocument()
    expect(screen.getByText('20 / 20')).toBeInTheDocument()
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

    render(<ProgressStep scanId="scan-1" />)

    expect(screen.getByText(/aktualizacja co kilka sekund/i)).toBeInTheDocument()
  })

  it('shows an error message when the hook reports one', () => {
    mockScanEvents({ error: 'scan was never started' })

    render(<ProgressStep scanId="scan-1" />)

    expect(screen.getByText('scan was never started')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL with `Cannot find module './ProgressStep'`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/steps/ProgressStep.tsx
import { useScanEvents } from '../api/useScanEvents'

interface ProgressStepProps {
  scanId: string
}

export function ProgressStep({ scanId }: ProgressStepProps) {
  const { scan, source, error } = useScanEvents(scanId)

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-slate-400">Łączenie ze skanem…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.round((scan.completed_products / scan.total_products) * 100)
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed'

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Przebieg skanu</h1>
      <div className="h-3 w-full rounded-full bg-slate-800">
        <div
          className="h-3 rounded-full bg-emerald-500 transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-sm text-slate-300">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-slate-500">
          Połączenie na żywo zerwane — aktualizacja co kilka sekund.
        </p>
      )}
      {isTerminal && (
        <p className="text-sm font-medium text-emerald-400">
          {scan.status === 'done' ? 'Skan zakończony.' : 'Skan zakończony z błędami.'}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/steps/ProgressStep.tsx frontend/src/steps/ProgressStep.test.tsx
git commit -m "Add ProgressStep component"
```

---

## Task 7: Wire up `ScanWizard` in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `UploadStep` (Task 4), `ScopeEstimateStep` (Task 5), `ProgressStep` (Task 6).
- Produces: the wired-up `App` component — no new exports other than the default export
  other code already depends on (`main.tsx` imports `App` as the default export, unchanged).

- [ ] **Step 1: Write the failing test**

Replace the whole contents of `frontend/src/App.test.tsx` (the Task 1 smoke test's job is
done — this replaces it, not adds to it):

```tsx
// frontend/src/App.test.tsx
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
    await screen.findByText('0.05 USD')
    await userEvent.click(screen.getByRole('button', { name: 'Uruchom skan' }))

    await screen.findByRole('heading', { name: 'Przebieg skanu' })
    expect(screen.getByText('2 / 5')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `App.tsx` still renders only the placeholder text, so none of the step
headings/buttons exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/App.tsx
import { useState } from 'react'
import { UploadStep } from './steps/UploadStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'

type WizardStep = 'upload' | 'scope' | 'progress'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('scope')
          }}
        />
      )}
      {step === 'scope' && file && (
        <ScopeEstimateStep
          file={file}
          onStarted={(id) => {
            setScanId(id)
            setStep('progress')
          }}
        />
      )}
      {step === 'progress' && scanId && <ProgressStep scanId={scanId} />}
    </div>
  )
}

export default App
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (1 test) — and run the full suite once to confirm no regressions:
`cd frontend && npm test` should show all test files passing (Tasks 1-7 combined).

- [ ] **Step 5: Run the linter**

Run: `cd frontend && npm run lint`
Expected: clean (no errors). Fix anything oxlint flags (e.g. unused imports) before
committing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "Wire UploadStep, ScopeEstimateStep, and ProgressStep into the scan wizard"
```

---

## Self-Review Notes

- **Spec coverage:** three-screen linear wizard, no router, no data-fetching library — Task
  7's `App.tsx` (plain `useState` step switch). `POST /scans` never spends money — Task 5
  calls `createScan` (estimate only) separately from `startScan` (Task 5's second button).
  SSE with reconnect + polling fallback — Task 3. Error surfacing per step — Tasks 4-6 each
  render the relevant error. Vitest + RTL TDD — Task 1 sets up the harness, every later task
  follows RED→GREEN. Dev-server proxy for the backend — Task 1. Deliberately not covered
  (per the design spec, later sub-phases): column-mapping correction, the Report screen,
  live cost-so-far during a scan.
- **Placeholder scan:** none — every step has real code.
- **Type consistency:** `Scan`/`CreateScanResult`/`ScopeConfig`/`CostEstimate` (Task 2) are
  used with identical field names across `useScanEvents.ts` (Task 3), `UploadStep.tsx`
  (consumes nothing from these, just `File`), `ScopeEstimateStep.tsx` (Task 5),
  `ProgressStep.tsx` (Task 6), and `App.tsx` (Task 7). `onFileSelected`/`onStarted` callback
  names and signatures match between each step's definition and `App.tsx`'s usage.

## Next steps after this plan

Phase 5b (Report screen + backend margin aggregation) and Phase 5c (column-mapping
correction screen + backend preview endpoint) — each needs its own brainstorming session
before a plan, since both require new backend work this plan deliberately doesn't touch.
