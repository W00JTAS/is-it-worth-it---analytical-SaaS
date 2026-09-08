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
        <p className="text-sm text-muted-foreground">Connecting to the scan…</p>
      </div>
    )
  }

  const percent = scan.total_products > 0
    ? Math.min(100, Math.round((scan.completed_products / scan.total_products) * 100))
    : 0
  const isTerminal = scan.status === 'done' || scan.status === 'failed' || scan.status === 'paused'
  // Both non-success terminal states leave products behind. Saying how many turns
  // "something went wrong" into a number the user can act on — and the report below
  // lists exactly these as "not checked".
  const unchecked = Math.max(0, scan.total_products - scan.completed_products)
  // A failed scan can die before its first product completes (percent === 0), which would
  // translate the indicator fully out of the track and hide the red color entirely — floor it
  // so the failure is always visible, not just implied by 0/N text.
  const displayPercent = scan.status === 'failed' ? Math.max(percent, 4) : percent

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Scan in progress</h1>
      <Progress
        value={displayPercent}
        aria-label="Scan progress"
        indicatorClassName={scan.status === 'failed' ? 'bg-destructive' : undefined}
      />
      <p className="text-sm text-muted-foreground">
        {scan.completed_products} / {scan.total_products}
      </p>
      {source === 'polling' && (
        <p className="text-xs text-muted-foreground">
          Live connection lost — refreshing every few seconds.
        </p>
      )}
      {isTerminal && (
        <>
          <p
            className={`text-sm font-medium ${
              scan.status === 'failed'
                ? 'text-destructive'
                : scan.status === 'paused'
                  ? 'text-warning'
                  : 'text-success'
            }`}
          >
            {scan.status === 'done'
              ? 'Scan finished.'
              : scan.status === 'paused'
                ? `Scan paused — the provider's request limit is exhausted, leaving ${unchecked} of ${scan.total_products} products unchecked. Run the scan again later to finish them; everything already looked up is cached and will not be paid for twice.`
                : `Scan finished with errors, leaving ${unchecked} of ${scan.total_products} products unchecked. Check the API key for the configured provider, then run the scan again.`}
          </p>
          <Button type="button" onClick={() => onDone(scanId)}>
            View report
          </Button>
        </>
      )}
    </div>
  )
}
