import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ScanLocalMovieFileModal } from '@/components/ScanLocalMovieFileModal'
import type { ScannedFileMatch } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735); plain assignment avoids it.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 422 ? 'Unprocessable Entity' : '',
    json: async () => body,
  } as Response
}

function scannedFile(path: string, filename: string): ScannedFileMatch {
  return { path, filename, season: null, episode_number: null, episode: null, status: 'matched' }
}

describe('ScanLocalMovieFileModal — shared-root scan with multiple untracked candidates', () => {
  test('linking one row disables Link on every other still-matched row', async () => {
    const rows = [scannedFile('/movies/A.mkv', 'A.mkv'), scannedFile('/movies/B.mkv', 'B.mkv')]
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/scan-local-movie-file')) return mockResponse(rows)
      if (url.includes('/link-movie-file')) {
        const body = JSON.parse(String(init?.body)) as { path: string }
        return mockResponse({ id: 1, original_filename: body.path, status: 'matched' })
      }
      return mockResponse(null)
    })

    render(
      createElement(ScanLocalMovieFileModal, { showId: 1, onClose: vi.fn() }),
      { wrapper: makeWrapper() },
    )

    const linkButtons = await screen.findAllByRole('button', { name: 'Link' })
    expect(linkButtons).toHaveLength(2)

    fireEvent.click(linkButtons[0])

    // The row that was clicked shows "linked" and its button disappears; the
    // sibling row's Link button must become disabled instead of staying
    // clickable (which would just 422 — "movie already has a linked file").
    await waitFor(() => {
      expect(screen.getByText('linked')).toBeInTheDocument()
    })
    const remainingButtons = screen.getAllByRole('button', { name: 'Link' })
    expect(remainingButtons).toHaveLength(1)
    expect(remainingButtons[0]).toBeDisabled()
  })

  test('sibling row disables while a link request is still in flight, before it resolves', async () => {
    const rows = [scannedFile('/movies/A.mkv', 'A.mkv'), scannedFile('/movies/B.mkv', 'B.mkv')]
    let resolveLink: (() => void) | undefined
    const linkCalls: string[] = []
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/scan-local-movie-file')) return mockResponse(rows)
      if (url.includes('/link-movie-file')) {
        linkCalls.push(String(init?.body))
        await new Promise<void>((resolve) => {
          resolveLink = resolve
        })
        return mockResponse({ id: 1, original_filename: 'A.mkv', status: 'matched' })
      }
      return mockResponse(null)
    })

    render(
      createElement(ScanLocalMovieFileModal, { showId: 1, onClose: vi.fn() }),
      { wrapper: makeWrapper() },
    )

    const linkButtons = await screen.findAllByRole('button', { name: 'Link' })
    fireEvent.click(linkButtons[0])

    // Request A is still in flight (unresolved) — the sibling must already
    // be disabled here, not only after A succeeds. Otherwise a second click
    // on B fires a concurrent request that can race the backend's
    // "not already linked" check before either commits.
    await waitFor(() => {
      expect(linkButtons[1]).toBeDisabled()
    })

    fireEvent.click(linkButtons[1])
    expect(linkCalls).toHaveLength(1)

    resolveLink?.()
  })
})
