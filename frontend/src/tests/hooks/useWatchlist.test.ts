import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useWatchlist, useCreateWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
import type { WatchlistList } from '@/types/api'

const sample: WatchlistList = {
  id: 1,
  show_id: 42,
  status: 'watching',
  position: 0,
  created_at: new Date().toISOString(),
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useWatchlist', () => {
  test('returns watchlist entries from API', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([sample]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    const { result } = renderHook(() => useWatchlist(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data![0].show_id).toBe(42)
  })

  test('passes status filter as query param', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    renderHook(() => useWatchlist('watching'), { wrapper: makeWrapper() })
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('status=watching')
  })
})

describe('useCreateWatchlistEntry', () => {
  test('POSTs to /api/watchlist and returns the new entry', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ...sample, updated_at: new Date().toISOString() }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const { result } = renderHook(() => useCreateWatchlistEntry(), { wrapper: makeWrapper() })
    result.current.mutate({ show_id: 42, status: 'watching' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('/api/watchlist')
  })
})

describe('useDeleteWatchlistEntry', () => {
  test('sends DELETE to /api/watchlist/{id}', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 204 }))
    const { result } = renderHook(() => useDeleteWatchlistEntry(), { wrapper: makeWrapper() })
    result.current.mutate(1)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('/api/watchlist/1')
    expect(vi.mocked(fetch).mock.calls[0][1]?.method).toBe('DELETE')
  })
})
