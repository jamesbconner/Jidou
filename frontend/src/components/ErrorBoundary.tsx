import { Component, type ReactNode, type ErrorInfo } from 'react'

interface Props { children: ReactNode }
interface State { hasError: boolean; message: string }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message }
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    console.error('Uncaught error:', err, info)
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
