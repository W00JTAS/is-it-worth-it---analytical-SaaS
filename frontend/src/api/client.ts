import { ApiError } from './types'
import type { CreateScanResult, Scan, ScopeConfig } from './types'
import type {
  CostConfigInput,
  ProductPage,
  ReportSummary,
  ColumnMapping,
  CsvPreview,
} from './types'

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // Response body wasn't JSON (or was empty) — fall through to a generic message.
  }
  return `Request failed with status ${response.status}`
}

function appendColumnMapping(formData: FormData, mapping: ColumnMapping): void {
  if (mapping.name !== null) formData.append('name_column', mapping.name)
  if (mapping.wholesale_price !== null) formData.append('wholesale_price_column', mapping.wholesale_price)
  if (mapping.ean !== null) formData.append('ean_column', mapping.ean)
  if (mapping.category !== null) formData.append('category_column', mapping.category)
  if (mapping.sku !== null) formData.append('sku_column', mapping.sku)
}

export async function createScan(
  file: File,
  scope: ScopeConfig,
  columnMapping?: ColumnMapping,
): Promise<CreateScanResult> {
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
  if (columnMapping) appendColumnMapping(formData, columnMapping)

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

function costConfigParams(costConfig: CostConfigInput): Record<string, string> {
  return {
    commission_pct: costConfig.commissionPct,
    shipping_cost: costConfig.shippingCost,
    vat_pct: costConfig.vatPct,
    returns_pct: costConfig.returnsPct,
  }
}

export async function getReportSummary(
  scanId: string,
  costConfig: CostConfigInput,
): Promise<ReportSummary> {
  const params = new URLSearchParams(costConfigParams(costConfig))
  const response = await fetch(`/scans/${scanId}/report/summary?${params}`)
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}

export interface ReportProductsParams {
  category?: string
  status?: string
  sort?: string
  page?: number
  pageSize?: number
}

export async function getReportProducts(
  scanId: string,
  costConfig: CostConfigInput,
  params: ReportProductsParams = {},
): Promise<ProductPage> {
  const query = new URLSearchParams(costConfigParams(costConfig))
  if (params.category) query.set('category', params.category)
  if (params.status) query.set('status', params.status)
  if (params.sort) query.set('sort', params.sort)
  query.set('page', String(params.page ?? 1))
  query.set('page_size', String(params.pageSize ?? 50))

  const response = await fetch(`/scans/${scanId}/report/products?${query}`)
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}

export async function getCsvPreview(file: File, mappingOverride?: ColumnMapping): Promise<CsvPreview> {
  const formData = new FormData()
  formData.append('file', file)
  if (mappingOverride) appendColumnMapping(formData, mappingOverride)

  const response = await fetch('/csv/preview', { method: 'POST', body: formData })
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status)
  }
  return response.json()
}
