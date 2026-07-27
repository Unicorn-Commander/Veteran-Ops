import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  /** Changing this value resets the boundary — pass the route path so navigating
   * to a different page clears a crash on the previous one. */
  resetKey?: string
  children: ReactNode
}

interface State {
  error: Error | null
}

/** Catches render/lifecycle errors in the page below it and shows a recoverable
 * card INSTEAD of letting the throw unmount the whole React tree (which would
 * leave only the app's background — the exact failure we hit when a page rendered
 * a data object as a React child). The app shell stays put; only the page area is
 * replaced, and "Reload this page" gets the veteran back to work. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidUpdate(prev: Props) {
    // Route changed — clear the error so the next page renders fresh.
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null })
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface it for diagnosis; harmless in prod, invaluable in the console.
    // eslint-disable-next-line no-console
    console.error('Page error caught by ErrorBoundary:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto flex w-full max-w-xl flex-col items-center gap-4 p-6 py-16 text-center sm:py-24">
          <span
            aria-hidden
            className="flex h-14 w-14 items-center justify-center rounded-full bg-danger-soft text-danger"
          >
            <AlertTriangle size={26} />
          </span>
          <div className="space-y-1.5">
            <h1 className="text-xl font-bold text-txt">This page hit a snag</h1>
            <p className="text-sm leading-relaxed text-muted">
              Something went wrong while showing this page. Your records are safe and untouched — reloading almost
              always clears it.
            </p>
          </div>
          <button type="button" onClick={() => window.location.reload()} className="vo-btn-primary">
            <RefreshCw size={16} /> Reload this page
          </button>
          {import.meta.env.DEV && (
            <pre className="mt-2 max-w-full overflow-x-auto rounded-control border border-line bg-surface2 p-3 text-left text-xs text-muted">
              {this.state.error.message}
            </pre>
          )}
        </div>
      )
    }
    return this.props.children
  }
}
