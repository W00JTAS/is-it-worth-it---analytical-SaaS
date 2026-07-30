import { useScanEvents } from '../api/useScanEvents'

interface ProgressStepProps {
  scanId: string
  onDone: (scanId: string) => void
}

export function ProgressStep({ scanId, onDone }: ProgressStepProps) {
  const { scan, source, error } = useScanEvents(scanId)

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-slate-400">Łączenie ze skanem…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.round((scan.completed_products / scan.total_products) * 100)
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed'

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-slate-100">Przebieg skanu</h1>
      <div className="h-3 w-full rounded-full bg-slate-800">
        <div
          className="h-3 rounded-full bg-emerald-500 transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-sm text-slate-300">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-slate-500">
          Połączenie na żywo zerwane — aktualizacja co kilka sekund.
        </p>
      )}
      {isTerminal && (
        <>
          <p
            className={`text-sm font-medium ${
              scan.status === 'failed' ? 'text-red-400' : 'text-emerald-400'
            }`}
          >
            {scan.status === 'done' ? 'Skan zakończony.' : 'Skan zakończony z błędami.'}
          </p>
          <button
            type="button"
            onClick={() => onDone(scanId)}
            className="rounded-md bg-emerald-600 px-4 py-2 font-medium text-slate-950"
          >
            Zobacz raport
          </button>
        </>
      )}
    </div>
  )
}
