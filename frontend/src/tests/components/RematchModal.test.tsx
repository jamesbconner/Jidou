import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { RematchModal } from '@/components/RematchModal'
import type { FileRead, ShowSearchResult } from '@/types/api'

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
  return { ok: status >= 200 && status < 300, status, statusText: '', json: async () => body } as Response
}

// Everything other than the local search: /config is an object, show lists are arrays.
function fallback(url: string): Response {
  if (url.startsWith('/api/config')) return mockResponse({ media_paths: {} })
  return mockResponse([])
}

const unmatchedFile = {
  id: 100,
  original_filename: 'Example.Show.S01E01.mkv',
  status: 'unmatched',
  parsed_show_name: 'Example Show',
} as unknown as FileRead

const hit: ShowSearchResult = {
  id: 7,
  tmdb_id: 700,
  title: 'Example Show',
  media_type: 'tv',
  content_type: 'anime',
  local_path: '/media/anime/Example Show (2019)',
  matched_on: 'title',
}

// Switching to Library clears the search box (existing behaviour), so type the query.
function switchToLibraryAndSearch() {
  fireEvent.click(screen.getByRole('button', { name: 'Library' }))
  fireEvent.change(screen.getByPlaceholderText('Search your library…'), {
    target: { value: 'Example Show' },
  })
}

describe('RematchModal library search', () => {
  test('does not claim "no results" while the local search is still in flight', async () => {
    let resolveSearch: (r: Response) => void = () => {}
    vi.mocked(fetch).mockImplementation((input) => {
      const url = String(input)
      if (url.startsWith('/api/shows/search?')) {
        return new Promise<Response>((resolve) => {
          resolveSearch = resolve
        })
      }
      return Promise.resolve(fallback(url))
    })

    render(<RematchModal file={unmatchedFile} onClose={() => {}} />, { wrapper: makeWrapper() })
    switchToLibraryAndSearch()

    // Wait for the debounced request to start, then check the pending state.
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(([u]) => String(u).startsWith('/api/shows/search?')),
      ).toBe(true),
    )
    expect(screen.queryByText('No library shows found.')).not.toBeInTheDocument()

    resolveSearch(mockResponse([]))
    await waitFor(() => expect(screen.getByText('No library shows found.')).toBeInTheDocument())
  })

  test('lists local matches with their existing folder', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      if (url.startsWith('/api/shows/search?')) return mockResponse([hit])
      return fallback(url)
    })

    render(<RematchModal file={unmatchedFile} onClose={() => {}} />, { wrapper: makeWrapper() })
    switchToLibraryAndSearch()

    await waitFor(() => expect(screen.getByText('Example Show')).toBeInTheDocument())
    expect(screen.queryByText('No library shows found.')).not.toBeInTheDocument()
  })

  test('switching to Library does not replay the TMDB query against the library', async () => {
    vi.mocked(fetch).mockImplementation(async (input) => fallback(String(input)))

    render(<RematchModal file={unmatchedFile} onClose={() => {}} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Library' }))
    await new Promise((r) => setTimeout(r, 400))

    const searched = vi
      .mocked(fetch)
      .mock.calls.some(([u]) => String(u).startsWith('/api/shows/search?'))
    expect(searched).toBe(false)
    expect(screen.queryByText('No library shows found.')).not.toBeInTheDocument()
  })
})
