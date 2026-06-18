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
        <div className="p-6 bg-red-50 border border-red-200 rounded-lg">
          <h2 className="text-lg font-semibold text-red-700">Something went wrong</h2>
          <p className="text-sm text-red-600 mt-1">{this.state.message}</p>
          <button
            className="mt-4 px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
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
