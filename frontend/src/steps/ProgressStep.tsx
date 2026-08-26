import { useScanEvents } from '../api/useScanEvents'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'

interface ProgressStepProps {
  scanId: string
  onDone: (scanId: string) => void
}

export function ProgressStep({ scanId, onDone }: ProgressStepProps) {
  const { scan, source, error } = useScanEvents(scanId)

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-destructive">{error}</p>
      </div>
    )
  }

  if (!scan) {
    return (
      <div className="mx-auto max-w-md p-8">
        <p className="text-sm text-muted-foreground">Łączenie ze skanem…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.min(100, Math.round((scan.completed_products / scan.total_products) * 100))
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed'
  // A failed scan can die before its first product completes (percent === 0), which would
  // translate the indicator fully out of the track and hide the red color entirely — floor it
  // so the failure is always visible, not just implied by 0/N text.
  const displayPercent = scan.status === 'failed' ? Math.max(percent, 4) : percent

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Przebieg skanu</h1>
      <Progress
        value={displayPercent}
        aria-label="Postęp skanu"
        indicatorClassName={scan.status === 'failed' ? 'bg-destructive' : undefined}
      />
      <p className="text-sm text-muted-foreground">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-muted-foreground">
          Połączenie na żywo zerwane — aktualizacja co kilka sekund.
        </p>
      )}
      {isTerminal && (
        <>
          <p
            className={`text-sm font-medium ${
              scan.status === 'failed' ? 'text-destructive' : 'text-success'
            }`}
          >
            {scan.status === 'done' ? 'Skan zakończony.' : 'Skan zakończony z błędami.'}
          </p>
          <Button type="button" onClick={() => onDone(scanId)}>
            Zobacz raport
          </Button>
        </>
      )}
    </div>
  )
}
