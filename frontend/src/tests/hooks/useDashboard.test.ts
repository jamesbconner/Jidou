import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import {
  useRecentShows,
  useRecentMovies,
  useRecentEpisodes,
  useDashboardGenres,
} from '@/hooks/useDashboard'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

function mockResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: '', json: async () => body } as Response
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('useRecentShows', () => {
  test('requests with sort, content_type, genre, and limit query params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    const { result } = renderHook(
      () => useRecentShows({ sort: 'release', contentType: 'anime', genre: 'Action', limit: 24 }),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('/api/dashboard/recent-shows')
    expect(url).toContain('sort=release')
    expect(url).toContain('content_type=anime')
    expect(url).toContain('genre=Action')
    expect(url).toContain('limit=24')
  })

  test('omits content_type and genre params when empty', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    const { result } = renderHook(
      () => useRecentShows({ sort: 'tracked', contentType: '', genre: '', limit: 12 }),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).not.toContain('content_type=')
    expect(url).not.toContain('genre=')
  })

  test('returns the fetched shows', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([{ id: 1, title: 'Show A' }]))
    const { result } = renderHook(
      () => useRecentShows({ sort: 'tracked', contentType: '', genre: '', limit: 12 }),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
  })
})

describe('useRecentMovies', () => {
  test('requests recent-movies with sort, genre, and limit query params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    const { result } = renderHook(
      () => useRecentMovies({ sort: 'release', genre: 'Action', limit: 24 }),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('/api/dashboard/recent-movies')
    expect(url).toContain('sort=release')
    expect(url).toContain('genre=Action')
    expect(url).toContain('limit=24')
    expect(url).not.toContain('content_type=')
  })

  test('omits genre param when empty', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    const { result } = renderHook(() => useRecentMovies({ sort: 'tracked', genre: '', limit: 12 }), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).not.toContain('genre=')
  })

  test('returns the fetched movies', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([{ id: 1, title: 'Movie A' }]))
    const { result } = renderHook(() => useRecentMovies({ sort: 'tracked', genre: '', limit: 12 }), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
  })
})

describe('useRecentEpisodes', () => {
  test('requests recent-episodes with query params', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    const { result } = renderHook(
      () => useRecentEpisodes({ sort: 'tracked', contentType: 'tv', genre: '', limit: 6 }),
      { wrapper: makeWrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('/api/dashboard/recent-episodes')
    expect(url).toContain('sort=tracked')
    expect(url).toContain('content_type=tv')
    expect(url).toContain('limit=6')
  })
})

describe('useDashboardGenres', () => {
  test('fetches the genres list', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse(['Action', 'Drama']))
    const { result } = renderHook(() => useDashboardGenres(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/api/dashboard/genres')
    expect(result.current.data).toEqual(['Action', 'Drama'])
  })
})
