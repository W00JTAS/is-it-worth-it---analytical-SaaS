import { useRef, useState } from 'react'
import { createScan, startScan } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CreateScanResult, ScopeType } from '../api/types'

interface ScopeEstimateStepProps {
  file: File
  columnMapping: ColumnMapping
  onStarted: (scanId: string) => void
}

// Standard Polish plural rules for "produkt": 1 -> singular, 2-4 (excluding
// 12-14) -> "few" form, everything else (0, 5+, 12-14) -> "many" form.
function pluralizeProdukt(n: number): string {
  if (n === 1) return 'produkt'
  const lastDigit = n % 10
  const lastTwo = n % 100
  if (lastDigit >= 2 && lastDigit <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return 'produkty'
  return 'produktów'
}

export function ScopeEstimateStep({ file, columnMapping, onStarted }: ScopeEstimateStepProps) {
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
  // Guards against a stale `createScan` response overwriting a newer one. The
  // fields are disabled while a request is in flight (see `isEstimating`
  // below), which is the primary fix — this counter is defense in depth in
  // case that disabling is ever bypassed or removed.
  const estimateRequestIdRef = useRef(0)
  const fieldsDisabled = isEstimating || isStarting

  // Any change to the scope config after an estimate exists invalidates that
  // estimate — clear it (and the refresh choice tied to it) so the UI can't
  // show a stale estimate while `handleStart` would launch the OLD config.
  function clearStaleEstimate() {
    setResult(null)
    setForceRefreshStale(false)
  }

  function handleScopeTypeChange(next: ScopeType) {
    clearStaleEstimate()
    setScopeType(next)
  }

  function handleSamplePerCategoryChange(value: string) {
    clearStaleEstimate()
    setSamplePerCategory(value)
  }

  function handleMaxDeliveryDaysChange(value: number) {
    clearStaleEstimate()
    setMaxDeliveryDays(value)
  }

  function handleMaxConcurrencyChange(value: number) {
    clearStaleEstimate()
    setMaxConcurrency(value)
  }

  function handleStalenessThresholdChange(value: number) {
    clearStaleEstimate()
    setStalenessThresholdDays(value)
  }

  async function handleEstimate() {
    const requestId = ++estimateRequestIdRef.current
    setError(null)
    setIsEstimating(true)
    try {
      const created = await createScan(
        file,
        {
          scopeType,
          samplePerCategory: scopeType === 'sample' ? Number(samplePerCategory) : undefined,
          market: 'PL',
          maxDeliveryDays,
          maxConcurrency,
          stalenessThresholdDays,
        },
        columnMapping,
      )
      // Discard this response if a newer request has since superseded it —
      // otherwise a stale estimate could win the race and be shown/started
      // against a config the user has since changed.
      if (estimateRequestIdRef.current === requestId) {
        setResult(created)
      }
    } catch (err) {
      if (estimateRequestIdRef.current === requestId) {
        setError(err instanceof ApiError ? err.message : 'Nie udało się oszacować kosztu')
      }
    } finally {
      if (estimateRequestIdRef.current === requestId) {
        setIsEstimating(false)
      }
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

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Zakres skanu</h1>

      <fieldset className="flex flex-col gap-2 text-sm text-slate-300">
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="scope"
            checked={scopeType === 'full'}
            onChange={() => handleScopeTypeChange('full')}
            disabled={fieldsDisabled}
          />
          Pełny skan
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="scope"
            checked={scopeType === 'sample'}
            onChange={() => handleScopeTypeChange('sample')}
            disabled={fieldsDisabled}
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
              onChange={(e) => handleSamplePerCategoryChange(e.target.value)}
              disabled={fieldsDisabled}
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
          onChange={(e) => handleMaxDeliveryDaysChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Limit współbieżności
        <input
          type="number"
          min={1}
          value={maxConcurrency}
          onChange={(e) => handleMaxConcurrencyChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24 rounded border border-slate-700 bg-slate-900 p-1 text-slate-100"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-slate-300">
        Próg nieświeżości (dni)
        <input
          type="number"
          min={0}
          value={stalenessThresholdDays}
          onChange={(e) => handleStalenessThresholdChange(Number(e.target.value))}
          disabled={fieldsDisabled}
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
            Bez odświeżania:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_without_refresh} USD (~{result.estimate.seconds_without_refresh}s)
            </span>
          </p>
          <p>
            Z odświeżaniem:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_with_refresh} USD (~{result.estimate.seconds_with_refresh}s)
            </span>
          </p>
          {result.overlapping_count > 0 && (
            <p>
              {result.overlapping_count} {pluralizeProdukt(result.overlapping_count)} w tym skanie
              nakładają się z poprzednimi skanami.
            </p>
          )}
          {result.stale_count > 0 && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={forceRefreshStale}
                onChange={(e) => setForceRefreshStale(e.target.checked)}
                disabled={fieldsDisabled}
              />
              Odśwież nieświeże ({result.stale_count} {pluralizeProdukt(result.stale_count)} z nich nie
              sprawdzano od dawna)
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
