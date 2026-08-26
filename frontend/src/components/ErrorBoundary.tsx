import { Component, type ReactNode, type ErrorInfo } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; message: string }

// React.lazy() caches a rejected dynamic import() on the component reference
// itself, so re-rendering it after a failed chunk load (stale hash from a
// new deploy, or a transient network blip) throws the exact same cached
// rejection -- the boundary's Retry button can reset its own state, but
// can't make the same lazy component re-fetch. Only a hard reload does.
//
// The error message is browser-specific, not a shared error type/code:
// Chrome/Edge say "Failed to fetch dynamically imported module", Firefox
// says "error loading dynamically imported module", and Safari says
// "Importing a module script failed" -- none share a common substring, so
// this has to match all three phrasings individually.
const CHUNK_LOAD_ERROR = /dynamically imported module|importing a module script failed/i
const RELOAD_GUARD_KEY = 'jidou.chunkLoadReloadAt'
const RELOAD_GUARD_WINDOW_MS = 10_000

function shouldAutoReload(err: Error): boolean {
  if (!CHUNK_LOAD_ERROR.test(err.message)) return false
  const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
  return Date.now() - last > RELOAD_GUARD_WINDOW_MS
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message }
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('Uncaught error:', err, info)

    // Auto-reload once for a genuine chunk-load failure -- picks up the new
    // deploy's asset manifest instead of leaving a long-lived tab stuck.
    // Guarded by a short time window (not a permanent per-session flag) so a
    // reload that doesn't fix it (a real network outage, not a stale chunk)
    // falls through to the normal error UI instead of loop-reloading, while
    // a later, unrelated failure still gets its own fresh reload attempt.
    if (shouldAutoReload(err)) {
      sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
      window.location.reload()
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-6 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded-lg">
          <h2 className="text-lg font-semibold text-red-700 dark:text-red-300">Something went wrong</h2>
          <p className="text-sm text-red-600 dark:text-red-400 mt-1">{this.state.message}</p>
          <button
            className="mt-4 px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700 dark:hover:bg-red-500"
            onClick={() => this.setState({ hasError: false, message: '' })}
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
