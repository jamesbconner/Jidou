import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import {
  useResolveCandidates,
  type SearchMode,
} from '@/components/resolveFile/useResolveCandidates'

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

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

const suggestion = {
  tmdb_id: 900,
  title: 'Suggested Show',
  media_type: 'tv',
  overview: '',
  poster_path: null,
  first_air_date: '2019-04-01',
  vote_average: 7,
}

/** Routes the hook's endpoints and returns the ordered request log. */
function mockApi(): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input)
    log.push(url)
    if (url === '/api/files/5/tmdb-suggestions') {
      return mockResponse({ query: 'q', results: [suggestion] })
    }
    if (url.startsWith('/api/shows/tmdb/search?')) {
      return mockResponse({
        results: [
          { id: 1, name: 'Hit', media_type: 'tv', overview: '', poster_path: null, vote_average: 1 },
          { id: 2, name: 'Someone', media_type: 'person', overview: '', poster_path: null, vote_average: 1 },
        ],
      })
    }
    if (url.startsWith('/api/shows/tmdb/')) {
      return mockResponse({
        id: 1668,
        title: 'Looked Up Movie',
        overview: '',
        poster_path: null,
        release_date: '2004-09-22',
        vote_average: 8,
      })
    }
    if (url.startsWith('/api/shows/search?')) return mockResponse([])
    return mockResponse([])
  })
  return log
}

interface Props {
  mode: SearchMode
  query: string
  tmdbId: number | null
}

function renderCandidates(initial: Props) {
  return renderHook(
    (p: Props) =>
      useResolveCandidates({
        mode: p.mode,
        fileId: 5,
        query: p.query,
        tmdbId: p.tmdbId,
        tmdbMediaType: 'movie',
        parsedName: 'Parsed Name',
      }),
    { wrapper: wrapper(), initialProps: initial },
  )
}

describe('useResolveCandidates', () => {
  test('suggestions mode loads suggestions and the parsed-name library search only', async () => {
    const log = mockApi()
    const { result } = renderCandidates({ mode: 'suggestions', query: 'typed', tmdbId: 1668 })

    await waitFor(() => expect(result.current.candidates).toHaveLength(1))
    expect(result.current.candidates[0]).toEqual({
      key: '900-tv',
      source: 'tmdb',
      tmdb: suggestion,
    })
    expect(log).toContain('/api/files/5/tmdb-suggestions')
    expect(log).toContain('/api/shows/search?query=Parsed%20Name&limit=6')
    expect(log.some((u) => u.includes('/tmdb/search'))).toBe(false)
    expect(log.some((u) => u.startsWith('/api/shows/tmdb/1668'))).toBe(false)
  })

  test('switching to tmdb_id makes no further suggestions request and uses the details response', async () => {
    const log = mockApi()
    const { result, rerender } = renderCandidates({ mode: 'suggestions', query: '', tmdbId: null })
    await waitFor(() => expect(result.current.candidates).toHaveLength(1))
    const suggestionRequests = () => log.filter((u) => u.includes('tmdb-suggestions')).length
    expect(suggestionRequests()).toBe(1)

    rerender({ mode: 'tmdb_id', query: '', tmdbId: 1668 })

    await waitFor(() => expect(result.current.candidates[0]?.tmdb?.title).toBe('Looked Up Movie'))
    expect(suggestionRequests()).toBe(1)
    expect(result.current.candidates).toEqual([
      {
        key: '1668-movie',
        source: 'tmdb',
        tmdb: {
          tmdb_id: 1668,
          title: 'Looked Up Movie',
          media_type: 'movie',
          overview: '',
          poster_path: null,
          first_air_date: '2004-09-22',
          vote_average: 8,
        },
      },
    ])
    expect(log).toContain('/api/shows/tmdb/1668?media_type=movie')
    // The library search follows the mode: no query in tmdb_id mode.
    expect(result.current.localCandidates).toEqual([])
  })

  test('tmdb_id mode with no parsed id makes no details request', async () => {
    const log = mockApi()
    const { result } = renderCandidates({ mode: 'tmdb_id', query: '', tmdbId: null })
    await new Promise((r) => setTimeout(r, 50))
    expect(log).toEqual([])
    expect(result.current.candidates).toEqual([])
    expect(result.current.isLoading).toBe(false)
  })

  test('title mode searches TMDB for the debounced query and keeps only tv/movie hits', async () => {
    const log = mockApi()
    const { result } = renderCandidates({ mode: 'title', query: 'Hit Show', tmdbId: null })

    await waitFor(() => expect(result.current.candidates).toHaveLength(1))
    expect(result.current.candidates[0].tmdb?.title).toBe('Hit')
    expect(result.current.error).toBeNull()
    expect(log).toContain('/api/shows/tmdb/search?query=Hit%20Show&media_type=multi')
    expect(log.some((u) => u.includes('tmdb-suggestions'))).toBe(false)
  })

  test('title mode with a one-character query makes no request', async () => {
    const log = mockApi()
    renderCandidates({ mode: 'title', query: 'A', tmdbId: null })
    await new Promise((r) => setTimeout(r, 400))
    expect(log).toEqual([])
  })
})
