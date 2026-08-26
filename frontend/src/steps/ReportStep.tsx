import { useEffect, useRef, useState } from 'react'
import { getReportProducts, getReportSummary } from '../api/client'
import { ApiError } from '../api/types'
import type { CostConfigInput, ProductRow, ReportSummary, ProductPage } from '../api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SELECT_CLASS } from '@/components/ui/selectClass'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

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
    <div className="flex flex-col gap-2 rounded-lg bg-muted p-4 text-sm text-muted-foreground">
      {row.offer ? (
        <>
          <p>
            Sprzedawca: <span className="text-foreground">{row.offer.seller}</span>
          </p>
          <p>
            Źródło:{' '}
            <a
              href={row.offer.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-foreground underline underline-offset-4"
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
      {row.anomaly_flag && <p className="text-warning">Flaga: {row.anomaly_flag}</p>}
      {row.margin_matrix && (
        // native table: nested inside a bg-muted panel, shadcn Table's hover/overflow chrome would be noise here
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
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
    <div className="rounded-lg border border-border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="grid w-full grid-cols-1 gap-1 p-4 text-left md:grid-cols-[1fr_140px_100px_140px] md:items-center md:gap-4"
      >
        <span className="text-sm font-medium text-foreground">{row.name}</span>
        <span className="text-xs text-muted-foreground md:text-sm">{row.category}</span>
        <span className="text-sm tabular-nums text-foreground md:text-right">{formatPct(margin)}</span>
        <span className="text-xs text-muted-foreground md:text-sm">{statusLabel(row)}</span>
      </button>
      {expanded && (
        <div className="border-t border-border p-4">
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
    <div className="mx-auto flex max-w-3xl flex-col gap-12 p-8">
      <h1 className="text-xl font-semibold text-foreground">Raport</h1>

      <section className="flex flex-col items-center gap-2 text-center">
        {isLoading ? (
          <p className="text-2xl font-medium text-muted-foreground">Liczenie…</p>
        ) : verdictValue !== null ? (
          <>
            <p
              className={`text-6xl font-semibold tabular-nums ${
                verdictPositive ? 'text-success' : 'text-destructive'
              }`}
            >
              {verdictPositive ? '+' : ''}
              {formatPct(verdictValue)}
            </p>
            <p className="text-sm text-muted-foreground">
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
          <p className="text-2xl font-medium text-muted-foreground">Brak danych do policzenia</p>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <div className="divide-y divide-border rounded-lg border border-border bg-card">
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
            Prowizja
            <Input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.commissionPct}
              onChange={(e) => setCostConfig({ ...costConfig, commissionPct: e.target.value })}
              className="w-28 text-right"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
            Wysyłka
            <Input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.shippingCost}
              onChange={(e) => setCostConfig({ ...costConfig, shippingCost: e.target.value })}
              className="w-28 text-right"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
            VAT
            <Input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.vatPct}
              onChange={(e) => setCostConfig({ ...costConfig, vatPct: e.target.value })}
              className="w-28 text-right"
            />
          </label>
          <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
            Zwroty
            <Input
              type="number"
              step="0.01"
              min={0}
              value={costConfig.returnsPct}
              onChange={(e) => setCostConfig({ ...costConfig, returnsPct: e.target.value })}
              className="w-28 text-right"
            />
          </label>
        </div>
        <Button type="button" onClick={recalculate} disabled={isLoading} className="self-start">
          Przelicz
        </Button>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </section>

      {summary && (
        <section className="flex flex-wrap gap-2">
          {summary.counts.no_offer > 0 && (
            <span className="rounded-md bg-muted px-3 py-1 text-xs text-warning">
              {summary.counts.no_offer} bez oferty
            </span>
          )}
          {summary.counts.anomaly > 0 && (
            <span className="rounded-md bg-muted px-3 py-1 text-xs text-warning">
              {summary.counts.anomaly} oflagowanych
            </span>
          )}
          {summary.counts.currency_mismatch > 0 && (
            <span className="rounded-md bg-muted px-3 py-1 text-xs text-warning">
              {summary.counts.currency_mismatch} innej waluty
            </span>
          )}
          {summary.counts.not_checked > 0 && (
            <span className="rounded-md bg-muted px-3 py-1 text-xs text-warning">
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
              <div key={row.scenario_pct} className="rounded-lg border border-border bg-card p-6">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  {formatPct(row.scenario_pct)}
                </p>
                <p
                  className={`text-3xl font-semibold tabular-nums ${
                    row.avg_margin_pct === null
                      ? 'text-muted-foreground'
                      : positive
                        ? 'text-success'
                        : 'text-destructive'
                  }`}
                >
                  {formatPct(row.avg_margin_pct)}
                </p>
                <p className="text-xs text-muted-foreground">{row.profitable_count} rentownych</p>
              </div>
            )
          })}
        </section>
      )}

      {summary && summary.category_table.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-muted-foreground">Kategorie</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="font-normal text-muted-foreground">Kategoria</TableHead>
                <TableHead className="text-right font-normal text-muted-foreground">Policzone</TableHead>
                <TableHead className="text-right font-normal text-muted-foreground">Wykluczone</TableHead>
                <TableHead className="text-right font-normal text-muted-foreground">Śr. marża</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.category_table.map((row) => (
                <TableRow key={row.category}>
                  <TableCell className="whitespace-normal text-foreground">{row.category}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{row.computable_count}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{row.excluded_count}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">
                    {formatPct(row.avg_margin_pct)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {productsError && !productPage && <p className="text-sm text-destructive">{productsError}</p>}

      {productPage && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-medium text-muted-foreground">Produkty</h2>
          <div className="flex flex-wrap gap-3 text-sm">
            <label className="flex items-center gap-2 text-muted-foreground">
              Kategoria
              <select
                value={category}
                onChange={(e) => handleCategoryChange(e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">Wszystkie</option>
                {Array.from(new Set(summary?.category_table.map((r) => r.category) ?? [])).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-muted-foreground">
              Status
              <select
                value={status}
                onChange={(e) => handleStatusChange(e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="">Wszystkie</option>
                <option value="computable">Policzone</option>
                <option value="no_offer">Bez oferty</option>
                <option value="anomaly">Oflagowane</option>
                <option value="currency_mismatch">Inna waluta</option>
                <option value="not_checked">Nie sprawdzono</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-muted-foreground">
              Sortowanie
              <select
                value={sort}
                onChange={(e) => handleSortChange(e.target.value)}
                className={SELECT_CLASS}
              >
                <option value="category">Kategoria</option>
                <option value="name">Nazwa</option>
                <option value="margin_desc">Marża malejąco</option>
                <option value="margin_asc">Marża rosnąco</option>
              </select>
            </label>
          </div>

          {productsError && <p className="text-sm text-destructive">{productsError}</p>}

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

          <div className="flex items-center justify-between text-sm text-muted-foreground">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handlePrevPage}
              disabled={productPage.page <= 1}
            >
              Poprzednia
            </Button>
            <span>
              Strona {productPage.page} z {Math.max(1, Math.ceil(productPage.total / productPage.page_size))}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleNextPage}
              disabled={productPage.page * productPage.page_size >= productPage.total}
            >
              Następna
            </Button>
          </div>
        </section>
      )}
    </div>
  )
}
