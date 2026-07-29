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
