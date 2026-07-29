import { useState } from 'react'
import type { ChangeEvent } from 'react'

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
      <h1 className="text-xl font-semibold text-slate-100">Wgraj katalog</h1>
      <label className="flex flex-col gap-2 text-sm text-slate-300" htmlFor="csv-upload">
        Plik CSV od hurtowni
        <input
          id="csv-upload"
          type="file"
          accept=".csv"
          onChange={handleChange}
          className="rounded-md border border-slate-700 bg-slate-900 p-2 text-slate-100 file:mr-3 file:rounded file:border-0 file:bg-emerald-600 file:px-3 file:py-1.5 file:text-slate-950 file:font-medium"
        />
      </label>
      {file && <p className="text-sm text-slate-400">{file.name}</p>}
      <button
        type="button"
        disabled={!file}
        onClick={() => file && onFileSelected(file)}
        className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
      >
        Dalej
      </button>
    </div>
  )
}
