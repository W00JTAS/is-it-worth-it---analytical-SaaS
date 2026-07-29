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
