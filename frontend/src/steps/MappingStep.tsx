import { useCallback, useEffect, useRef, useState } from 'react'
import { getCsvPreview } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CsvPreview } from '../api/types'

const EMPTY_MAPPING: ColumnMapping = {
  name: null,
  wholesale_price: null,
  ean: null,
  category: null,
  sku: null,
}

interface MappingStepProps {
  file: File
  onConfirmed: (mapping: ColumnMapping) => void
}

export function MappingStep({ file, onConfirmed }: MappingStepProps) {
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  // Guards against a stale loadPreview response overwriting a newer one --
  // e.g. the user edits a dropdown while a previously-triggered "Odśwież
  // podgląd" request is still in flight. The dropdowns are also disabled
  // while `isLoading` (primary fix, see the `disabled={isLoading}` selects
  // below); this counter is defense in depth in case that disabling is ever
  // bypassed or removed. Mirrors ScopeEstimateStep's estimateRequestIdRef.
  const previewRequestIdRef = useRef(0)

  const loadPreview = useCallback(async (override?: ColumnMapping) => {
    const requestId = ++previewRequestIdRef.current
    setError(null)
    setIsLoading(true)
    try {
      const result = await getCsvPreview(file, override)
      if (previewRequestIdRef.current === requestId) {
        setPreview(result)
        // Only adopt the backend's `mapping` on the INITIAL load (no
        // override -- pure auto-detection, nothing local to preserve yet).
        // On a user-initiated refresh (override provided), the local
        // `mapping` state IS the current source of truth for what the user
        // has chosen -- adopting the response here would silently revert an
        // explicitly-cleared field (e.g. SKU) back to its auto-detected
        // value, since the backend's `or`-based merge can't distinguish
        // "not sent" from "explicitly cleared to null".
        if (override === undefined) {
          setMapping(result.mapping)
        }
      }
    } catch (err) {
      if (previewRequestIdRef.current === requestId) {
        setError(err instanceof ApiError ? err.message : 'Nie udało się wczytać podglądu pliku')
      }
    } finally {
      if (previewRequestIdRef.current === requestId) {
        setIsLoading(false)
      }
    }
  }, [file])

  // Runs once, on mount, for pure auto-detection. Every later refresh is the
  // explicit "Odśwież podgląd" button below -- never triggered by editing a
  // dropdown, matching the explicit-recompute pattern used throughout this wizard.
  useEffect(() => {
    loadPreview()
  }, [loadPreview])

  function handleFieldChange(field: keyof ColumnMapping, value: string) {
    setMapping({ ...mapping, [field]: value || null })
  }

  function handleRefresh() {
    loadPreview(mapping)
  }

  const requiredFilled = Boolean(
    mapping.name && mapping.wholesale_price && mapping.ean && mapping.category,
  )

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-12 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Mapowanie kolumn</h1>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {preview && (
        <>
          <section className="flex flex-col gap-4">
            <div className="divide-y divide-slate-800/60 rounded-2xl border border-slate-800 bg-slate-900/40">
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Nazwa
                <select
                  value={mapping.name ?? ''}
                  onChange={(e) => handleFieldChange('name', e.target.value)}
                  disabled={isLoading}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Cena hurtowa
                <select
                  value={mapping.wholesale_price ?? ''}
                  onChange={(e) => handleFieldChange('wholesale_price', e.target.value)}
                  disabled={isLoading}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                EAN
                <select
                  value={mapping.ean ?? ''}
                  onChange={(e) => handleFieldChange('ean', e.target.value)}
                  disabled={isLoading}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                Kategoria
                <select
                  value={mapping.category ?? ''}
                  onChange={(e) => handleFieldChange('category', e.target.value)}
                  disabled={isLoading}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-slate-300">
                SKU (opcjonalne)
                <select
                  value={mapping.sku ?? ''}
                  onChange={(e) => handleFieldChange('sku', e.target.value)}
                  disabled={isLoading}
                  className="w-56 rounded-lg border border-slate-700 bg-slate-950 p-2 text-slate-100"
                >
                  <option value="">— brak —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isLoading}
              className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:bg-slate-700 disabled:text-slate-400"
            >
              Odśwież podgląd
            </button>
          </section>

          <section className="flex flex-col gap-2 text-sm text-slate-300">
            <p>
              {preview.parsed_count} / {preview.total_rows} wierszy sparsowanych poprawnie
            </p>
            {preview.warnings.length > 0 && (
              <ul className="list-inside list-disc text-amber-400">
                {preview.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
                {preview.warning_count > preview.warnings.length && (
                  <li>...i {preview.warning_count - preview.warnings.length} więcej</li>
                )}
              </ul>
            )}
          </section>

          {preview.sample_rows.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-slate-400">Przykładowe wiersze</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-800/60 text-left text-slate-500">
                      {preview.headers.map((h) => (
                        <th key={h} className="py-2 pr-4 font-normal">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample_rows.map((row, i) => (
                      <tr key={i} className="border-b border-slate-800/60">
                        {preview.headers.map((h) => (
                          <td key={h} className="py-2 pr-4 text-slate-300">{row[h] ?? ''}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <button
            type="button"
            onClick={() => onConfirmed(mapping)}
            disabled={!requiredFilled || isLoading}
            className="self-start rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
          >
            Dalej
          </button>
        </>
      )}
    </div>
  )
}
