import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './types'
import { createScan, getScan, startScan, getReportSummary, getReportProducts, getCsvPreview } from './client'
import type { ColumnMapping, ScopeConfig } from './types'

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

describe('getReportSummary', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends cost config as query params and returns the parsed summary', async () => {
    const summary = {
      counts: { total: 1, computable: 1, not_checked: 0, no_offer: 0, currency_mismatch: 0, anomaly: 0 },
      category_table: [],
      scenario_matrix: [],
    }
    vi.mocked(fetch).mockResolvedValue(jsonResponse(summary))

    const result = await getReportSummary('scan-1', {
      commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
    })

    expect(result).toEqual(summary)
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/scans/scan-1/report/summary?')
    expect(url).toContain('commission_pct=0.10')
    expect(url).toContain('shipping_cost=15.00')
    expect(url).toContain('vat_pct=0.23')
    expect(url).toContain('returns_pct=0.02')
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'bad request' }, 400))

    await expect(
      getReportSummary('scan-1', {
        commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
      }),
    ).rejects.toMatchObject({ status: 400 })
  })
})

describe('getReportProducts', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends pagination, filter, and sort params', async () => {
    const page = { total: 0, page: 2, page_size: 10, rows: [] }
    vi.mocked(fetch).mockResolvedValue(jsonResponse(page))

    const result = await getReportProducts(
      'scan-1',
      { commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02' },
      { category: 'Electronics', status: 'computable', sort: 'margin_desc', page: 2, pageSize: 10 },
    )

    expect(result).toEqual(page)
    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/scans/scan-1/report/products?')
    expect(url).toContain('category=Electronics')
    expect(url).toContain('status=computable')
    expect(url).toContain('sort=margin_desc')
    expect(url).toContain('page=2')
    expect(url).toContain('page_size=10')
  })

  it('defaults page to 1 and page_size to 50 when not given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ total: 0, page: 1, page_size: 50, rows: [] }))

    await getReportProducts('scan-1', {
      commissionPct: '0.10', shippingCost: '15.00', vatPct: '0.23', returnsPct: '0.02',
    })

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('page=1')
    expect(url).toContain('page_size=50')
  })
})

const CSV_PREVIEW = {
  headers: ['Name', 'Wholesale price', 'EAN', 'Category'],
  mapping: { name: 'Name', wholesale_price: 'Wholesale price', ean: 'EAN', category: 'Category', sku: null },
  sample_rows: [{ Name: 'Produkt A', 'Wholesale price': '10,00', EAN: '5901234123457', Category: 'Electronics' }],
  total_rows: 1,
  parsed_count: 1,
  warnings: [],
  warning_count: 0,
}

describe('getCsvPreview', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the file with no mapping fields when no override is given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(CSV_PREVIEW))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })

    const result = await getCsvPreview(file)

    expect(result).toEqual(CSV_PREVIEW)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/csv/preview')
    expect(init?.method).toBe('POST')
    const body = init?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
    expect(body.get('name_column')).toBeNull()
  })

  it('posts only the non-null mapping fields when an override is given', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(CSV_PREVIEW))
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })
    const mapping: ColumnMapping = {
      name: 'Name', wholesale_price: 'Wholesale price', ean: 'EAN', category: 'Category', sku: null,
    }

    await getCsvPreview(file, mapping)

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = init?.body as FormData
    expect(body.get('name_column')).toBe('Name')
    expect(body.get('wholesale_price_column')).toBe('Wholesale price')
    expect(body.get('ean_column')).toBe('EAN')
    expect(body.get('category_column')).toBe('Category')
    expect(body.get('sku_column')).toBeNull()
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'CSV file has no header row' }, 400))
    const file = new File([''], 'catalog.csv', { type: 'text/csv' })

    await expect(getCsvPreview(file)).rejects.toMatchObject({ status: 400 })
  })
})

describe('createScan with a column mapping', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('includes mapping fields in the form data when columnMapping is provided', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        scan_id: 'scan-1', status: 'estimated', scope_type: 'full',
        total_products: 1, completed_products: 0,
        estimate: {
          queries_without_refresh: 1, queries_with_refresh: 1,
          cost_usd_without_refresh: '0.01', cost_usd_with_refresh: '0.01',
          seconds_without_refresh: 1, seconds_with_refresh: 1,
        },
        overlapping_count: 0, stale_count: 0, warnings: [],
      }),
    )
    const file = new File(['a,b\n1,2'], 'catalog.csv', { type: 'text/csv' })
    const mapping: ColumnMapping = {
      name: 'Name', wholesale_price: 'Wholesale price', ean: 'EAN', category: 'Category', sku: 'SKU',
    }
    const scope: ScopeConfig = {
      scopeType: 'full', market: 'PL', maxDeliveryDays: 5, maxConcurrency: 5, stalenessThresholdDays: 14,
    }

    await createScan(file, scope, mapping)

    const [, init] = vi.mocked(fetch).mock.calls[0]
    const body = init?.body as FormData
    expect(body.get('name_column')).toBe('Name')
    expect(body.get('sku_column')).toBe('SKU')
  })
})
