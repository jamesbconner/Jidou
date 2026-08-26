import { render, screen } from '@testing-library/react'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'

function Boom({ message }: { message: string }): never {
  throw new Error(message)
}

describe('ErrorBoundary', () => {
  let reload: ReturnType<typeof vi.fn>
  let originalLocation: Location

  beforeEach(() => {
    // jsdom's real location.reload throws "not implemented" -- replace the
    // whole object so it's spy-able, and restore it after each test.
    originalLocation = window.location
    reload = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, reload },
    })
    sessionStorage.clear()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
    vi.restoreAllMocks()
  })

  test('renders children when there is no error', () => {
    render(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  test('shows the fallback UI for a non-chunk-load error, without reloading', () => {
    render(
      <ErrorBoundary>
        <Boom message="boom" />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('boom')).toBeInTheDocument()
    expect(reload).not.toHaveBeenCalled()
  })

  test.each([
    ['Chrome/Edge', 'Failed to fetch dynamically imported module: http://localhost/assets/Settings.js'],
    ['Firefox', 'error loading dynamically imported module'],
    ['Safari', 'Importing a module script failed'],
  ])('auto-reloads once on a %s chunk-load error', (_browser, message) => {
    render(
      <ErrorBoundary>
        <Boom message={message} />
      </ErrorBoundary>,
    )
    expect(reload).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('jidou.chunkLoadReloadAt')).not.toBeNull()
  })

  test('does not reload again within the guard window', () => {
    sessionStorage.setItem('jidou.chunkLoadReloadAt', String(Date.now()))
    render(
      <ErrorBoundary>
        <Boom message="Failed to fetch dynamically imported module: http://localhost/assets/Settings.js" />
      </ErrorBoundary>,
    )
    expect(reload).not.toHaveBeenCalled()
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})
