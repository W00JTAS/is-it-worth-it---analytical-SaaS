import { lazy, Suspense, useState } from 'react'
import { AppShell } from './AppShell'
import { UploadStep } from './steps/UploadStep'
import { StepErrorBoundary } from './components/StepErrorBoundary'
import type { ColumnMapping } from './api/types'
import type { WizardStep } from './wizardSteps'

const MappingStep = lazy(() => import('./steps/MappingStep').then((m) => ({ default: m.MappingStep })))
const ScopeEstimateStep = lazy(() =>
  import('./steps/ScopeEstimateStep').then((m) => ({ default: m.ScopeEstimateStep }))
)
const ProgressStep = lazy(() => import('./steps/ProgressStep').then((m) => ({ default: m.ProgressStep })))
const ReportStep = lazy(() => import('./steps/ReportStep').then((m) => ({ default: m.ReportStep })))

function StepFallback() {
  return (
    <div className="p-8">
      <p role="status" aria-live="polite" className="text-sm text-muted-foreground">
        Loading…
      </p>
    </div>
  )
}

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [columnMapping, setColumnMapping] = useState<ColumnMapping | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <AppShell currentStep={step}>
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('mapping')
          }}
          onSampleSelected={(selected, mapping) => {
            setFile(selected)
            setColumnMapping(mapping)
            setStep('scope')
          }}
        />
      )}
      <StepErrorBoundary>
        <Suspense fallback={<StepFallback />}>
          {step === 'mapping' && file && (
            <MappingStep
              file={file}
              onConfirmed={(mapping) => {
                setColumnMapping(mapping)
                setStep('scope')
              }}
            />
          )}
          {step === 'scope' && file && columnMapping && (
            <ScopeEstimateStep
              file={file}
              columnMapping={columnMapping}
              onStarted={(id) => {
                setScanId(id)
                setStep('progress')
              }}
            />
          )}
          {step === 'progress' && scanId && (
            <ProgressStep scanId={scanId} onDone={() => setStep('report')} />
          )}
          {step === 'report' && scanId && <ReportStep scanId={scanId} />}
        </Suspense>
      </StepErrorBoundary>
    </AppShell>
  )
}

export default App
