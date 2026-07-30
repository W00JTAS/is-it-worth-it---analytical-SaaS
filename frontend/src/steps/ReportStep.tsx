import { useEffect, useRef, useState } from 'react'
import { getReportProducts, getReportSummary } from '../api/client'
import { ApiError } from '../api/types'
import type { CostConfigInput, ProductRow, ReportSummary, ProductPage } from '../api/types'

const STORAGE_KEY = 'isItWorthIt.costConfig'

const DEFAULT_COST_CONFIG: CostConfigInput = {
  commissionPct: '0.15',
  shippingCost: '0.00',
  vatPct: '0.23',
  returnsPct: '0.05',
}

const PAGE_SIZE = 25

const STATUS_LABELS: Record<string, string> = {
  computable: 'Policzone',
  not_checked: 'Nie sprawdzono',
  no_offer: 'Brak oferty',
  currency_mismatch: 'Inna waluta',
  anomaly: 'Oflagowane',
}

function statusLabel(row: ProductRow): string {
  return STATUS_LABELS[row.computable ? 'computable' : row.exclusion_reason ?? 'no_offer']
}

function marginAtZero(row: ProductRow): string | null {
  const match = row.margin_matrix?.find((m) => m.scenario_pct === '0.00')
  return match ? match.margin_pct : null
}

function loadStoredCostConfig(): CostConfigInput {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_COST_CONFIG
    const parsed = JSON.parse(raw)
    return {
      commissionPct: String(parsed.commissionPct ?? DEFAULT_COST_CONFIG.commissionPct),
      shippingCost: String(parsed.shippingCost ?? DEFAULT_COST_CONFIG.shippingCost),
      vatPct: String(parsed.vatPct ?? DEFAULT_COST_CONFIG.vatPct),
      returnsPct: String(parsed.returnsPct ?? DEFAULT_COST_CONFIG.returnsPct),
    }
  } catch {
    return DEFAULT_COST_CONFIG
  }
}

export function formatPct(value: string | null): string {
  if (value === null) return '—'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function ProductDetail({ row }: { row: ProductRow }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-slate-900/60 p-4 text-sm text-slate-300">
      {row.offer ? (
        <>
          <p>
            Sprzedawca: <span className="text-slate-100">{row.offer.seller}</span>
          </p>
          <p>
            Źródło:{' '}
            <a
              href={row.offer.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-emerald-400 underline"
            >
              {row.offer.source_url}
            </a>
          </p>
          <p>Czas dostawy: {row.offer.delivery_days} dni</p>
          <p>Pewność: {(row.offer.confidence * 100).toFixed(0)}%</p>
        </>
      ) : (
        <p>Brak znalezionej oferty.</p>
      )}
      {row.anomaly_flag && <p className="text-amber-400">Flaga: {row.anomaly_flag}</p>}
      {row.margin_matrix && (
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="font-normal">Scenariusz</th>
              <th className="text-right font-normal">Marża %</th>
              <th className="text-right font-normal">Cena sprzedaży</th>
            </tr>
          </thead>
          <tbody>
            {row.margin_matrix.map((m) => (
              <tr key={m.scenario_pct}>
                <td>{formatPct(m.scenario_pct)}</td>
                <td className="text-right tabular-nums">{formatPct(m.margin_pct)}</td>
                <td className="text-right tabular-nums">{m.sale_price}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ProductRowCard({
  row, expanded, onToggle,
}: {
  row: ProductRow
  expanded: boolean
  onToggle: () => void
}) {
  const margin = marginAtZero(row)
  return (
    <div className="rounded-xl border border-slate-800/60">
      <button
        type="button"
        onClick={onToggle}
        className="grid w-full grid-cols-1 gap-1 p-4 text-left md:grid-cols-[1fr_140px_100px_140px] md:items-center md:gap-4"
      >
        <span className="text-sm font-medium text-slate-100">{row.name}</span>
        <span className="text-xs text-slate-400 md:text-sm">{row.category}</span>
        <span className="text-sm tabular-nums text-slate-300 md:text-right">{formatPct(margin)}</span>
        <span className="text-xs text-slate-400 md:text-sm">{statusLabel(row)}</span>
      </button>
      {expanded && (
        <div className="border-t border-slate-800/60 p-4">
          <ProductDetail row={row} />
        </div>
      )}
    </div>
  )
}

interface ReportStepProps {
  scanId: string
}

export function ReportStep({ scanId }: ReportStepProps) {
  const [costConfig, setCostConfig] = useState<CostConfigInput>(loadStoredCostConfig)
  // The cost config values actually confirmed by the last successful
  // "Przelicz" click (or the initial mount load) — as opposed to `costConfig`,
  // which tracks every keystroke in the input fields below. Product-list
  // requests (filter/sort/pager) must use this snapshot, never the live,
  // possibly-unconfirmed `costConfig`, so a mid-edit field never silently
  // gets sent to the backend. See recalculate().
  const [appliedCostConfig, setAppliedCostConfig] = useState<CostConfigInput>(loadStoredCostConfig)
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Starts true: the mount effect below always kicks off an initial
  // recalculate() before the user can interact, so there is no real "idle"
  // frame — starting false would let the empty-state text flash for one
  // render before the effect flips this to true.
  const [isLoading, setIsLoading] = useState(true)
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState('category')
  const [productPage, setProductPage] = useState<ProductPage | null>(null)
  const [productsError, setProductsError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // Discard a response if a newer request of the same kind has since
  // superseded it — mirrors ScopeEstimateStep's estimateRequestIdRef. Two
  // separate counters (one per request type) keep each guard scoped to the
  // specific request it protects.
  const summaryRequestIdRef = useRef(0)
  const productsRequestIdRef = useRef(0)

  async function loadProducts(
    overrides: { category?: string; status?: string; sort?: string; page: number },
    costConfigOverride?: CostConfigInput,
  ) {
    const requestId = ++productsRequestIdRef.current
    setProductsError(null)
    const effectiveCategory = overrides.category ?? category
    const effectiveStatus = overrides.status ?? status
    const effectiveSort = overrides.sort ?? sort
    // Read the confirmed snapshot, not the live (possibly unconfirmed)
    // costConfig — except right after recalculate() confirms a new value,
    // where the override is passed explicitly to avoid a stale-closure read
    // of appliedCostConfig before its setState has committed.
    const effectiveCostConfig = costConfigOverride ?? appliedCostConfig
    try {
      const result = await getReportProducts(scanId, effectiveCostConfig, {
        category: effectiveCategory || undefined,
        status: effectiveStatus || undefined,
        sort: effectiveSort,
        page: overrides.page,
        pageSize: PAGE_SIZE,
      })
      if (productsRequestIdRef.current === requestId) {
        setProductPage(result)
      }
    } catch (err) {
      if (productsRequestIdRef.current === requestId) {
        setProductsError(err instanceof ApiError ? err.message : 'Nie udało się wczytać produktów')
      }
    }
  }

  function handleCategoryChange(value: string) {
    setCategory(value)
    loadProducts({ category: value, page: 1 })
  }

  function handleStatusChange(value: string) {
    setStatus(value)
    loadProducts({ status: value, page: 1 })
  }

  function handleSortChange(value: string) {
    setSort(value)
    loadProducts({ sort: value, page: 1 })
  }

  function handlePrevPage() {
    const current = productPage?.page ?? 1
    loadProducts({ page: Math.max(1, current - 1) })
  }

  function handleNextPage() {
    const current = productPage?.page ?? 1
    loadProducts({ page: current + 1 })
  }

  async function recalculate() {
    const requestId = ++summaryRequestIdRef.current
    setError(null)
    setIsLoading(true)
    try {
      const result = await getReportSummary(scanId, costConfig)
      if (summaryRequestIdRef.current !== requestId) return
      setSummary(result)
      setAppliedCostConfig(costConfig)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(costConfig))
      await loadProducts({ page: 1 }, costConfig)
    } catch (err) {
      if (summaryRequestIdRef.current === requestId) {
        setError(err instanceof ApiError ? err.message : 'Nie udało się policzyć raportu')
      }
    } finally {
      if (summaryRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }

  // Runs once per scan (not per keystroke in the cost-config card below —
  // that's deliberate, see recalculate() and the "Przelicz" button).
  useEffect(() => {
    recalculate()
  }, [scanId])

  const referenceScenario = summary?.scenario_matrix.find((row) => row.scenario_pct === '0.00') ?? null
  const verdictValue = referenceScenario?.avg_margin_pct ?? null
  const verdictPositive = verdictValue !== null && Number(verdictValue) > 0

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-16 p-8">
      <section className="flex flex-col items-center gap-2 text-center">
        {isLoading ? (
          <p className="text-2xl font-medium text-slate-400">Liczenie…</p>
        ) : verdictValue !== null ? (
          <>
            <p
              className={`text-6xl font-semibold tabular-nums ${
                verdictPositive ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {verdictPositive ? '+' : ''}
              {formatPct(verdictValue)}
            </p>
            <p className="text-sm text-slate-400">
              {referenceScenario?.profitable_count ?? 0} / {summary?.counts.computable ?? 0}{' '}
              produktów rentownych przy cenie rynkowej
            </p>
          </>
        ) : error ? null : (
          // Only reachable once a request has actually succeeded with zero
          // computable products, or before anything has ever loaded (and no
          // error/loading is in progress) — never while loading or after a
          // failed request, so this text no longer contradicts the error
          // message or flashes during every load.
          <p className="text-2xl font-medium text-slate-400">Brak danych do policzenia</p>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <div className="divide-y divide-slate-800/60 rounded-2xl border border-slate-800 bg-slate-900/40">
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Prowizja
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.commissionPct}
              onChange={(e) => setCostConfig({ ...costConfig, commissionPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Wysyłka
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.shippingCost}
              onChange={(e) => setCostConfig({ ...costConfig, shippingCost: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            VAT
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.vatPct}
              onChange={(e) => setCostConfig({ ...costConfig, vatPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
            Zwroty
            <input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.returnsPct}
              onChange={(e) => setCostConfig({ ...costConfig, returnsPct: e.target.value })}
              className="w-28 rounded-lg border border-slate-700 bg-slate-950 p-2 text-right text-slate-100"
            />
          </label>
        </div>
        <button
          type="button"
          onClick={recalculate}
          disabled={isLoading}
          className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
        >
          Przelicz
        </button>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </section>

      {summary && (
        <section className="flex flex-wrap gap-2">
          {summary.counts.no_offer > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.no_offer} bez oferty
            </span>
          )}
          {summary.counts.anomaly > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.anomaly} oflagowanych
            </span>
          )}
          {summary.counts.currency_mismatch > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.currency_mismatch} innej waluty
            </span>
          )}
          {summary.counts.not_checked > 0 && (
            <span className="rounded-full bg-slate-900 px-3 py-1 text-xs text-amber-400">
              {summary.counts.not_checked} nie sprawdzono
            </span>
          )}
        </section>
      )}

      {summary && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {summary.scenario_matrix.map((row) => {
            const positive = row.avg_margin_pct !== null && Number(row.avg_margin_pct) > 0
            return (
              <div key={row.scenario_pct} className="rounded-2xl border border-slate-800 p-6">
                <p className="text-xs uppercase tracking-wide text-slate-500">
                  {formatPct(row.scenario_pct)}
                </p>
                <p
                  className={`text-3xl font-semibold tabular-nums ${
                    row.avg_margin_pct === null
                      ? 'text-slate-500'
                      : positive
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                  }`}
                >
                  {formatPct(row.avg_margin_pct)}
                </p>
                <p className="text-xs text-slate-500">{row.profitable_count} rentownych</p>
              </div>
            )
          })}
        </section>
      )}

      {summary && summary.category_table.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-slate-400">Kategorie</h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800/60 text-left text-slate-500">
                <th className="py-2 font-normal">Kategoria</th>
                <th className="py-2 text-right font-normal">Policzone</th>
                <th className="py-2 text-right font-normal">Wykluczone</th>
                <th className="py-2 text-right font-normal">Śr. marża</th>
              </tr>
            </thead>
            <tbody>
              {summary.category_table.map((row) => (
                <tr key={row.category} className="border-b border-slate-800/60">
                  <td className="py-2 text-slate-200">{row.category}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">{row.computable_count}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">{row.excluded_count}</td>
                  <td className="py-2 text-right tabular-nums text-slate-300">
                    {formatPct(row.avg_margin_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {productsError && !productPage && <p className="text-sm text-red-400">{productsError}</p>}

      {productPage && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-medium text-slate-400">Produkty</h2>
          <div className="flex flex-wrap gap-3 text-sm">
            <label className="flex items-center gap-2 text-slate-300">
              Kategoria
              <select
                value={category}
                onChange={(e) => handleCategoryChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="">Wszystkie</option>
                {Array.from(new Set(summary?.category_table.map((r) => r.category) ?? [])).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-slate-300">
              Status
              <select
                value={status}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="">Wszystkie</option>
                <option value="computable">Policzone</option>
                <option value="no_offer">Bez oferty</option>
                <option value="anomaly">Oflagowane</option>
                <option value="currency_mismatch">Inna waluta</option>
                <option value="not_checked">Nie sprawdzono</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-slate-300">
              Sortowanie
              <select
                value={sort}
                onChange={(e) => handleSortChange(e.target.value)}
                className="rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
              >
                <option value="category">Kategoria</option>
                <option value="name">Nazwa</option>
                <option value="margin_desc">Marża malejąco</option>
                <option value="margin_asc">Marża rosnąco</option>
              </select>
            </label>
          </div>

          {productsError && <p className="text-sm text-red-400">{productsError}</p>}

          <div className="flex flex-col gap-2">
            {productPage.rows.map((row) => (
              <ProductRowCard
                key={row.id}
                row={row}
                expanded={expandedId === row.id}
                onToggle={() => setExpandedId(expandedId === row.id ? null : row.id)}
              />
            ))}
          </div>

          <div className="flex items-center justify-between text-sm text-slate-400">
            <button
              type="button"
              onClick={handlePrevPage}
              disabled={productPage.page <= 1}
              className="rounded-md border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Poprzednia
            </button>
            <span>
              Strona {productPage.page} z {Math.max(1, Math.ceil(productPage.total / productPage.page_size))}
            </span>
            <button
              type="button"
              onClick={handleNextPage}
              disabled={productPage.page * productPage.page_size >= productPage.total}
              className="rounded-md border border-slate-700 px-3 py-1.5 disabled:opacity-40"
            >
              Następna
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
