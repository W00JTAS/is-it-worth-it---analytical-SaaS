import { Component, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

interface StepErrorBoundaryProps {
  children: ReactNode
}

interface StepErrorBoundaryState {
  hasError: boolean
}

// Catches a failed dynamic import from a lazy-loaded step (e.g. a stale chunk after a
// redeploy). Scoped below App's own state (file/columnMapping/scanId), so a caught error
// unmounts only the current step's subtree — the wizard's progress is not lost.
export class StepErrorBoundary extends Component<StepErrorBoundaryProps, StepErrorBoundaryState> {
  state: StepErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  handleRetry = () => {
    this.setState({ hasError: false })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8">
          <p className="text-sm text-destructive">Nie udało się załadować tego kroku.</p>
          <Button type="button" variant="outline" className="mt-3" onClick={this.handleRetry}>
            Spróbuj ponownie
          </Button>
        </div>
      )
    }

    return this.props.children
  }
}
