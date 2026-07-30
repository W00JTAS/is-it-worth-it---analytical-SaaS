import { useCallback, useEffect, useRef, useState } from 'react'
import { getCsvPreview } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CsvPreview } from '../api/types'
import { Button } from '@/components/ui/button'
import { PaginatedList } from '@/components/PaginatedList'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const EMPTY_MAPPING: ColumnMapping = {
  name: null,
  wholesale_price: null,
  ean: null,
  category: null,
  sku: null,
}

const SELECT_CLASS =
  'h-9 w-56 rounded-md border border-input bg-transparent px-3 py-1 text-sm text-foreground shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30'

interface MappingStepProps {
  file: File
  onConfirmed: (mapping: ColumnMapping) => void
}

export function MappingStep({ file, onConfirmed }: MappingStepProps) {
  const [preview, setPreview] = useState<CsvPreview | null>(null)
  const [mapping, setMapping] = useState<ColumnMapping>(EMPTY_MAPPING)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const previewRequestIdRef = useRef(0)

  const loadPreview = useCallback(async (override?: ColumnMapping) => {
    const requestId = ++previewRequestIdRef.current
    setError(null)
    setIsLoading(true)
    try {
      const result = await getCsvPreview(file, override)
      if (previewRequestIdRef.current === requestId) {
        setPreview(result)
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
      <h1 className="text-xl font-semibold text-foreground">Mapowanie kolumn</h1>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {preview && (
        <>
          <section className="flex flex-col gap-4">
            <div className="divide-y divide-border rounded-2xl border border-border bg-card">
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Nazwa
                <select
                  value={mapping.name ?? ''}
                  onChange={(e) => handleFieldChange('name', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Cena hurtowa
                <select
                  value={mapping.wholesale_price ?? ''}
                  onChange={(e) => handleFieldChange('wholesale_price', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                EAN
                <select
                  value={mapping.ean ?? ''}
                  onChange={(e) => handleFieldChange('ean', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                Kategoria
                <select
                  value={mapping.category ?? ''}
                  onChange={(e) => handleFieldChange('category', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— wybierz —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
              <label className="flex items-center justify-between gap-4 p-4 text-sm text-muted-foreground">
                SKU (opcjonalne)
                <select
                  value={mapping.sku ?? ''}
                  onChange={(e) => handleFieldChange('sku', e.target.value)}
                  disabled={isLoading}
                  className={SELECT_CLASS}
                >
                  <option value="">— brak —</option>
                  {preview.headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
              </label>
            </div>
            <Button type="button" onClick={handleRefresh} disabled={isLoading} className="self-start">
              Odśwież podgląd
            </Button>
          </section>

          <section className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>
              {preview.parsed_count} / {preview.total_rows} wierszy sparsowanych poprawnie
            </p>
            {preview.warnings.length > 0 && (
              <PaginatedList
                items={preview.warnings}
                pageSize={10}
                renderItem={(warning) => <span className="text-warning">{warning}</span>}
              />
            )}
            {preview.warning_count > preview.warnings.length && (
              <p>...i {preview.warning_count - preview.warnings.length} więcej</p>
            )}
          </section>

          {preview.sample_rows.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-muted-foreground">Przykładowe wiersze</h2>
              <Table>
                <TableHeader>
                  <TableRow>
                    {preview.headers.map((h) => (
                      <TableHead key={h}>{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.sample_rows.map((row, i) => (
                    <TableRow key={i}>
                      {preview.headers.map((h) => (
                        <TableCell key={h}>{row[h] ?? ''}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          )}

          <Button
            type="button"
            onClick={() => onConfirmed(mapping)}
            disabled={!requiredFilled || isLoading}
            className="self-start"
          >
            Dalej
          </Button>
        </>
      )}
    </div>
  )
}
