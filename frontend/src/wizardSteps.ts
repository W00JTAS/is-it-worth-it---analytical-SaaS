import { Activity, BarChart3, Columns3, Target, Upload, type LucideIcon } from 'lucide-react'

export type WizardStep = 'upload' | 'mapping' | 'scope' | 'progress' | 'report'

export interface WizardStepMeta {
  id: WizardStep
  label: string
  icon: LucideIcon
}

export const WIZARD_STEPS: readonly WizardStepMeta[] = [
  { id: 'upload', label: 'Upload', icon: Upload },
  { id: 'mapping', label: 'Mapowanie', icon: Columns3 },
  { id: 'scope', label: 'Zakres', icon: Target },
  { id: 'progress', label: 'Postęp', icon: Activity },
  { id: 'report', label: 'Raport', icon: BarChart3 },
]
