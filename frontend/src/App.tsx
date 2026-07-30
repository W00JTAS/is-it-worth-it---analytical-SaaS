import { useState } from 'react'
import { UploadStep } from './steps/UploadStep'
import { ScopeEstimateStep } from './steps/ScopeEstimateStep'
import { ProgressStep } from './steps/ProgressStep'
import { ReportStep } from './steps/ReportStep'

type WizardStep = 'upload' | 'scope' | 'progress' | 'report'

function App() {
  const [step, setStep] = useState<WizardStep>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [scanId, setScanId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {step === 'upload' && (
        <UploadStep
          onFileSelected={(selected) => {
            setFile(selected)
            setStep('scope')
          }}
        />
      )}
      {step === 'scope' && file && (
        <ScopeEstimateStep
          file={file}
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
