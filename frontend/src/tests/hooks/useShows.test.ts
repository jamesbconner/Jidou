import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useSearchShows, useLibraryIndex, showKeys } from '@/hooks/useShows'
import type { ShowList } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735) — property-descriptor
// manipulation on the native fetch/undici binding is implicated. A plain
// assignment achieves the same mockability without touching the native
// descriptor.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

function makeShow(overrides: Partial<ShowList> = {}): ShowList {
  return {
    id: 1,
    tmdb_id: 1396,
    title: 'Breaking Bad',
    media_type: 'tv',
    poster_path: null,
    vote_average: null,
    release_date: null,
    original_language: null,
    ...overrides,
  } as ShowList
}

describe('showKeys.search', () => {
  test('includes mediaType in the key so it does not collide with an unfiltered search', () => {
    expect(showKeys.search('breaking bad')).not.toEqual(showKeys.search('breaking bad', 'multi'))
  })

  test('is stable for the same query and mediaType', () => {
    expect(showKeys.search('breaking bad', 'multi')).toEqual(showKeys.search('breaking bad', 'multi'))
  })
})

describe('useSearchShows', () => {
  test('omits media_type from the URL when mediaType is not passed', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ results: [], total_results: 0, total_pages: 0, page: 1 }))
    renderHook(() => useSearchShows('breaking bad'), { wrapper: makeWrapper() })
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('query=breaking%20bad')
    expect(url).not.toContain('media_type')
  })

  test('includes media_type in the URL when mediaType is passed', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse({ results: [], total_results: 0, total_pages: 0, page: 1 }))
    renderHook(() => useSearchShows('breaking bad', 'multi'), { wrapper: makeWrapper() })
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('media_type=multi')
  })

  test('does not fire below the 2-character minimum', () => {
    renderHook(() => useSearchShows('a', 'multi'), { wrapper: makeWrapper() })
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('useLibraryIndex', () => {
  test('does not collide a tv show and a movie sharing the same raw tmdb_id', async () => {
    // TMDB uses separate id namespaces for tv and movie, so a numeric
    // tmdb_id alone is not a unique key across a search result set that can
    // contain both. Regression: a tv show and movie sharing id=1396 must
    // resolve to two distinct index entries, each independently retrievable
    // by its own tmdb_id:media_type key.
    const tvShow = makeShow({ id: 1, tmdb_id: 1396, title: 'Breaking Bad', media_type: 'tv' })
    const movie = makeShow({ id: 2, tmdb_id: 1396, title: 'Coach Carter', media_type: 'movie' })
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([tvShow, movie]))

    const { result } = renderHook(() => useLibraryIndex(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.size).toBe(2))

    expect(result.current.get('1396:tv')).toEqual(tvShow)
    expect(result.current.get('1396:movie')).toEqual(movie)
  })

  test('is empty before the library list has loaded', () => {
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}))
    const { result } = renderHook(() => useLibraryIndex(), { wrapper: makeWrapper() })
    expect(result.current.size).toBe(0)
  })
})
