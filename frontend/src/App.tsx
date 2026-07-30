import { useState } from 'react'
import { UploadStep } from './steps/UploadStep'
import { MappingStep } from './steps/MappingStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'
import type { ColumnMapping } from './api/types'

type WizardStep = 'upload' | 'mapping' | 'scope' | 'progress' | 'report'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [columnMapping, setColumnMapping] = useState<ColumnMapping | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
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
    </div>
  )
}

export default App
