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

// Duck-types the subset of the Fetch Response interface api/client.ts
// actually reads (.ok, .status, .json()) instead of constructing a real
// Response — the native/undici Response implementation triggers a worker
// crash on Node >=22.1.x (https://github.com/nodejs/node/issues/54735).
function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735) — property-descriptor
// manipulation on the native fetch/undici binding is implicated. A plain
// assignment achieves the same mockability without touching the native
// descriptor, and is restored explicitly since test files now share one
// global context (see vitest.config.ts isolate: false).
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('useWatchlist', () => {
  test('returns watchlist entries from API', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([sample]))
    const { result } = renderHook(() => useWatchlist(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(1)
    expect(result.current.data![0].show_id).toBe(42)
  })

  test('passes status filter as query param', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse([]))
    renderHook(() => useWatchlist('watching'), { wrapper: makeWrapper() })
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    const url = vi.mocked(fetch).mock.calls[0][0] as string
    expect(url).toContain('status=watching')
  })
})

describe('useCreateWatchlistEntry', () => {
  test('POSTs to /api/watchlist and returns the new entry', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ ...sample, updated_at: new Date().toISOString() }, 201),
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
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse(null, 204))
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

  test('POSTs a single batched request with 1-based positions', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(mockResponse(null, 204))

    // item.position values are intentionally stale to confirm they are not used —
    // the hook derives position from array order, not from item.position.
    const items = [makeEntry(1, 99), makeEntry(2, 99), makeEntry(3, 99)]
    const { result } = renderHook(() => useReorderWatchlist(), { wrapper: makeWrapper() })
    result.current.mutate(items)
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toContain('/api/watchlist/reorder')
    expect((init as RequestInit).method).toBe('POST')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual([
      { id: 1, position: 1 },
      { id: 2, position: 2 },
      { id: 3, position: 3 },
    ])
  })

  test('throws if the batched POST fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockResponse({ detail: 'Watchlist entries not found: [2]' }, 404),
    )

    const items = [makeEntry(1, 1), makeEntry(2, 2)]
    const { result } = renderHook(() => useReorderWatchlist(), { wrapper: makeWrapper() })
    result.current.mutate(items)
    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
