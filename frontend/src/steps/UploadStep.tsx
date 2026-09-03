import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Cpu, ToyBrick, UtensilsCrossed, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ColumnMapping } from '../api/types'

interface UploadStepProps {
  onFileSelected: (file: File) => void
  onSampleSelected: (file: File, columnMapping: ColumnMapping) => void
}

const SAMPLE_COLUMN_MAPPING: ColumnMapping = {
  name: 'nazwa', wholesale_price: 'cena', ean: 'ean', category: 'kategoria', sku: 'SKU',
}

interface SampleCategory {
  id: string
  label: string
  description: string
  icon: LucideIcon
}

const SAMPLE_CATEGORIES: readonly SampleCategory[] = [
  { id: 'kuchnia', label: 'Kuchnia i AGD', description: '25 realnych produktów AGD', icon: UtensilsCrossed },
  { id: 'zabawki', label: 'Zabawki', description: '25 realnych zabawek', icon: ToyBrick },
  { id: 'elektronika', label: 'Elektronika', description: '25 realnych produktów elektronicznych', icon: Cpu },
]

export function UploadStep({ onFileSelected, onSampleSelected }: UploadStepProps) {
  const [file, setFile] = useState<File | null>(null)
  const [loadingSampleId, setLoadingSampleId] = useState<string | null>(null)
  const [sampleError, setSampleError] = useState<string | null>(null)
  // Guards against a sample fetch that outlives this component -- e.g. the
  // user clicks a sample card, the fetch is slow, they upload their own file
  // instead (advancing `App` past `UploadStep`, unmounting it), then the
  // fetch resolves from a stale closure and would otherwise silently call
  // `onSampleSelected` after the fact.
  const isMountedRef = useRef(true)
  useEffect(() => {
    // Reset (not just rely on the useRef initializer) because React's
    // StrictMode double-invokes effects in development -- mount, cleanup,
    // mount again -- to surface exactly this class of bug. Without this
    // line, the cleanup from StrictMode's first simulated unmount leaves
    // isMountedRef.current permanently false for the component's real
    // lifetime, silently breaking every guarded code path below (observed:
    // the sample-loading state got stuck forever, since both the success
    // callback and the loading-state reset were skipped).
    isMountedRef.current = true
    return () => { isMountedRef.current = false }
  }, [])

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  async function handleSampleClick(category: SampleCategory) {
    setSampleError(null)
    setLoadingSampleId(category.id)
    try {
      const response = await fetch(`/samples/${category.id}.csv`)
      if (!response.ok) throw new Error(`sample fetch failed: ${response.status}`)
      const blob = await response.blob()
      if (!isMountedRef.current) return
      const sampleFile = new File([blob], `${category.id}.csv`, { type: 'text/csv' })
      onSampleSelected(sampleFile, SAMPLE_COLUMN_MAPPING)
    } catch {
      if (isMountedRef.current) setSampleError('Nie udało się wczytać przykładowej próbki')
    } finally {
      if (isMountedRef.current) setLoadingSampleId(null)
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-8 p-8">
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold text-foreground">Wgraj katalog</h1>
        <div className="flex flex-col gap-2">
          <Label htmlFor="csv-upload">Plik CSV od hurtowni</Label>
          <Input id="csv-upload" type="file" accept=".csv" onChange={handleChange} />
        </div>
        <Button type="button" disabled={!file} onClick={() => file && onFileSelected(file)}>
          Dalej
        </Button>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Nie masz jeszcze własnego pliku? Wypróbuj na przykładowej próbce:
        </p>
        {sampleError && <p className="text-sm text-destructive">{sampleError}</p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {SAMPLE_CATEGORIES.map((category) => (
            <Button
              key={category.id}
              type="button"
              variant="outline"
              disabled={loadingSampleId !== null}
              onClick={() => handleSampleClick(category)}
              className="flex h-auto flex-col items-start gap-2 border-border p-4 text-left whitespace-normal"
            >
              <category.icon className="size-5 text-muted-foreground" />
              <span className="font-medium text-foreground">{category.label}</span>
              <span className="text-xs font-normal text-muted-foreground">
                {loadingSampleId === category.id ? 'Wczytywanie…' : category.description}
              </span>
            </Button>
          ))}
        </div>
      </div>
    </div>
  )
}
