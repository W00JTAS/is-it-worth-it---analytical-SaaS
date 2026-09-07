import { Activity, BarChart3, Columns3, Target, Upload, type LucideIcon } from 'lucide-react'

export type WizardStep = 'upload' | 'mapping' | 'scope' | 'progress' | 'report'

export interface WizardStepMeta {
  id: WizardStep
  label: string
  icon: LucideIcon
}

export const WIZARD_STEPS: readonly WizardStepMeta[] = [
  { id: 'upload', label: 'Upload', icon: Upload },
  { id: 'mapping', label: 'Mapping', icon: Columns3 },
  { id: 'scope', label: 'Scope', icon: Target },
  { id: 'progress', label: 'Progress', icon: Activity },
  { id: 'report', label: 'Report', icon: BarChart3 },
]
