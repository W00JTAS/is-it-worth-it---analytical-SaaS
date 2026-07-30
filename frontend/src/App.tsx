import { useState } from 'react'
import { AppShell } from './AppShell'
import { UploadStep } from './steps/UploadStep'
import { MappingStep } from './steps/MappingStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'
import type { ColumnMapping } from './api/types'
import type { WizardStep } from './wizardSteps'

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
        />
      )}
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
    </AppShell>
  )
}

export default App
