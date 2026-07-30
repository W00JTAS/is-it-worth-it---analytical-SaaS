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

export interface CostConfigInput {
  commissionPct: string
  shippingCost: string
  vatPct: string
  returnsPct: string
}

export type ExclusionReason = 'not_checked' | 'no_offer' | 'currency_mismatch' | 'anomaly'

export interface ReportCounts {
  total: number
  computable: number
  not_checked: number
  no_offer: number
  currency_mismatch: number
  anomaly: number
}

export interface CategoryRow {
  category: string
  computable_count: number
  excluded_count: number
  avg_margin_pct: string | null
}

export interface ScenarioRow {
  scenario_pct: string
  avg_margin_pct: string | null
  profitable_count: number
}

export interface ReportSummary {
  counts: ReportCounts
  category_table: CategoryRow[]
  scenario_matrix: ScenarioRow[]
}

export interface MarginResult {
  scenario_pct: string
  sale_price: string
  net_revenue: string
  total_costs: string
  margin: string
  margin_pct: string
}

export interface ProductOffer {
  price: string
  currency: string
  seller: string
  source_url: string
  delivery_days: number
  confidence: number
  citations: string[]
}

export interface ProductRow {
  id: number
  external_id: string
  name: string
  category: string
  ean: string | null
  wholesale_price: string
  currency: string
  computable: boolean
  exclusion_reason: ExclusionReason | null
  anomaly_flag: string | null
  offer: ProductOffer | null
  margin_matrix: MarginResult[] | null
}

export interface ProductPage {
  total: number
  page: number
  page_size: number
  rows: ProductRow[]
}

export interface ColumnMapping {
  name: string | null
  wholesale_price: string | null
  ean: string | null
  category: string | null
  sku: string | null
}

export interface CsvPreview {
  headers: string[]
  mapping: ColumnMapping
  sample_rows: Record<string, string>[]
  total_rows: number
  parsed_count: number
  warnings: string[]
  warning_count: number
}
