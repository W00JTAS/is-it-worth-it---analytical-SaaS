import { useEffect, useState } from 'react'
import { getReportSummary } from '../api/client'
import { ApiError } from '../api/types'
import type { CostConfigInput, ReportSummary } from '../api/types'

const STORAGE_KEY = 'isItWorthIt.costConfig'

const DEFAULT_COST_CONFIG: CostConfigInput = {
  commissionPct: '0.15',
  shippingCost: '0.00',
  vatPct: '0.23',
  returnsPct: '0.05',
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

interface ReportStepProps {
  scanId: string
}

export function ReportStep({ scanId }: ReportStepProps) {
  const [costConfig, setCostConfig] = useState<CostConfigInput>(loadStoredCostConfig)
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  async function recalculate() {
    setError(null)
    setIsLoading(true)
    try {
      const result = await getReportSummary(scanId, costConfig)
      setSummary(result)
      localStorage.setItem(STORAGE_KEY, JSON.stringify(costConfig))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Nie udało się policzyć raportu')
    } finally {
      setIsLoading(false)
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
        {verdictValue === null ? (
          <p className="text-2xl font-medium text-slate-400">Brak danych do policzenia</p>
        ) : (
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
    </div>
  )
}
