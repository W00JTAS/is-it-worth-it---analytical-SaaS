import { useState } from 'react'
import type { ChangeEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface UploadStepProps {
  onFileSelected: (file: File) => void
}

export function UploadStep({ onFileSelected }: UploadStepProps) {
  const [file, setFile] = useState<File | null>(null)

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null)
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Wgraj katalog</h1>
      <div className="flex flex-col gap-2">
        <Label htmlFor="csv-upload">Plik CSV od hurtowni</Label>
        <Input id="csv-upload" type="file" accept=".csv" onChange={handleChange} />
      </div>
      {file && <p className="text-sm text-muted-foreground">{file.name}</p>}
      <Button type="button" disabled={!file} onClick={() => file && onFileSelected(file)}>
        Dalej
      </Button>
    </div>
  )
}
