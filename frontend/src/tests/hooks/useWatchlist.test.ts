import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useWatchlist, useCreateWatchlistEntry, useDeleteWatchlistEntry, useReorderWatchlist } from '@/hooks/useWatchlist'
import type { WatchlistList, WatchlistRead } from '@/types/api'

const sample: WatchlistList = {
  id: 1,
  show_id: 42,
  show: { title: 'Test Show', tmdb_id: 100, poster_path: null },
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

describe('useReorderWatchlist', () => {
  function makeEntry(id: number, position: number): WatchlistRead {
    return {
      id,
      show_id: id * 10,
      show: { title: `Show ${id}`, tmdb_id: id * 100, poster_path: null },
      status: 'planned',
      notes: null,
      position,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
  }

  test('PATCHes only entries whose position changed', async () => {
    const patchResponse = (id: number, pos: number) =>
      new Response(
        JSON.stringify({ ...makeEntry(id, pos), updated_at: new Date().toISOString() }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )

    // Entry 1 is already at position 1, entry 2 moves from 3 → 2, entry 3 moves from 2 → 3
    vi.mocked(fetch)
      .mockResolvedValueOnce(patchResponse(2, 2))
      .mockResolvedValueOnce(patchResponse(3, 3))

    const items = [makeEntry(1, 1), makeEntry(2, 3), makeEntry(3, 2)]
    const { result } = renderHook(() => useReorderWatchlist(), { wrapper: makeWrapper() })
    result.current.mutate(items)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const patchCalls = vi.mocked(fetch).mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === 'PATCH',
    )
    expect(patchCalls).toHaveLength(2)
    expect(patchCalls[0][0]).toContain('/api/watchlist/2')
    expect(patchCalls[1][0]).toContain('/api/watchlist/3')
  })

  test('sends no requests when order is unchanged', async () => {
    const items = [makeEntry(1, 1), makeEntry(2, 2)]
    const { result } = renderHook(() => useReorderWatchlist(), { wrapper: makeWrapper() })
    result.current.mutate(items)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(vi.mocked(fetch)).not.toHaveBeenCalled()
  })
})
