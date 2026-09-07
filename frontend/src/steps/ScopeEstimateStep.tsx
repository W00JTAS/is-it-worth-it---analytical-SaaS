import { useRef, useState } from 'react'
import { createScan, startScan } from '../api/client'
import { ApiError } from '../api/types'
import type { ColumnMapping, CreateScanResult, ScopeType } from '../api/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PaginatedList } from '@/components/PaginatedList'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ChevronDown } from 'lucide-react'

interface ScopeEstimateStepProps {
  file: File
  columnMapping: ColumnMapping
  onStarted: (scanId: string) => void
}

function pluralizeProduct(n: number): string {
  return n === 1 ? 'product' : 'products'
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
        setError(err instanceof ApiError ? err.message : 'Could not estimate the cost')
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
      setError(err instanceof ApiError ? err.message : 'Could not start the scan')
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-8">
      <h1 className="text-xl font-semibold text-foreground">Scan scope</h1>

      <fieldset className="flex flex-col gap-3 text-sm text-muted-foreground">
        <RadioGroup
          value={scopeType}
          onValueChange={(value) => handleScopeTypeChange(value as ScopeType)}
          disabled={fieldsDisabled}
        >
          <div className="flex items-center gap-2">
            <RadioGroupItem value="full" id="scope-full" />
            <Label htmlFor="scope-full">Full scan</Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem value="sample" id="scope-sample" />
            <Label htmlFor="scope-sample">Sample per category</Label>
          </div>
        </RadioGroup>
        {scopeType === 'sample' && (
          <div className="flex flex-col gap-1 pl-6">
            <Label htmlFor="sample-per-category">Products per category</Label>
            <Input
              id="sample-per-category"
              type="number"
              min={1}
              value={samplePerCategory}
              onChange={(e) => handleSamplePerCategoryChange(e.target.value)}
              disabled={fieldsDisabled}
              className="w-24"
            />
          </div>
        )}
      </fieldset>

      <div className="flex flex-col gap-1">
        <Label htmlFor="max-delivery-days">Delivery time limit (days)</Label>
        <Input
          id="max-delivery-days"
          type="number"
          min={1}
          value={maxDeliveryDays}
          onChange={(e) => handleMaxDeliveryDaysChange(Number(e.target.value))}
          disabled={fieldsDisabled}
          className="w-24"
        />
      </div>

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" className="group flex items-center gap-2 self-start px-0 text-sm text-muted-foreground">
            <ChevronDown className="size-4 transition-transform group-data-[state=open]:rotate-180" />
            Advanced settings
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-4 pt-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="max-concurrency">Concurrency limit</Label>
            <p className="text-xs text-muted-foreground">
              How many offers we check at once. Higher is faster, but more likely to hit the
              data provider's rate limits.
            </p>
            <Input
              id="max-concurrency"
              type="number"
              min={1}
              value={maxConcurrency}
              onChange={(e) => handleMaxConcurrencyChange(Number(e.target.value))}
              disabled={fieldsDisabled}
              className="w-24"
            />
          </div>

          <div className="flex flex-col gap-1">
            <Label htmlFor="staleness-threshold">Staleness threshold (days)</Label>
            <p className="text-xs text-muted-foreground">
              After how many days a price from an earlier scan counts as out of date and gets
              checked again instead of being reused from cache.
            </p>
            <Input
              id="staleness-threshold"
              type="number"
              min={0}
              value={stalenessThresholdDays}
              onChange={(e) => handleStalenessThresholdChange(Number(e.target.value))}
              disabled={fieldsDisabled}
              className="w-24"
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      {error && <p className="text-sm text-destructive">{error}</p>}

      {!result && (
        <Button type="button" onClick={handleEstimate} disabled={isEstimating} className="self-start">
          Estimate cost
        </Button>
      )}

      {result && (
        <div className="flex flex-col gap-3 rounded-md border border-border p-6 text-sm text-foreground">
          <p>
            No refresh:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_without_refresh} USD (~{result.estimate.seconds_without_refresh}s)
            </span>
          </p>
          <p>
            With refresh:{' '}
            <span className="font-semibold">
              {result.estimate.cost_usd_with_refresh} USD (~{result.estimate.seconds_with_refresh}s)
            </span>
          </p>
          {result.overlapping_count > 0 && (
            <p>
              {result.overlapping_count} {pluralizeProduct(result.overlapping_count)} in this scan
              overlap with earlier scans.
            </p>
          )}
          {result.stale_count > 0 && (
            <label className="flex items-center gap-2">
              <Checkbox
                checked={forceRefreshStale}
                onCheckedChange={(checked) => setForceRefreshStale(checked === true)}
                disabled={fieldsDisabled}
              />
              Refresh stale entries ({result.stale_count} {pluralizeProduct(result.stale_count)} have
              not been checked in a while)
            </label>
          )}
          {result.warnings.length > 0 && (
            <PaginatedList
              items={result.warnings}
              pageSize={10}
              renderItem={(warning) => <span className="text-warning">{warning}</span>}
            />
          )}
          <Button type="button" onClick={handleStart} disabled={isStarting} className="self-start">
            Run scan
          </Button>
        </div>
      )}
    </div>
  )
}
