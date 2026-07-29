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
