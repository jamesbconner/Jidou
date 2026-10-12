import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect } from 'vitest'
import { createElement } from 'react'
import { http, HttpResponse } from 'msw'
import { useShowDetailData } from '@/pages/showDetail/useShowDetailData'
import type { WatchlistRead } from '@/types/api'
import { startMswServer } from '@/tests/helpers/msw'

// DF-18: ShowDetail checks watchlist membership with GET /watchlist?show_id=
// instead of fetching up to 10,000 entries. The full list is fetched only
// once the show is known to be on the watchlist, because the Queue #N
// position select needs every entry in order.

const SHOW_ID = 42

function wlEntry(id: number, showId: number, position: number): WatchlistRead {
  return {
    id,
    show_id: showId,
    status: 'planned',
    notes: null,
    position,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    show: null,
    next_up: null,
  } as unknown as WatchlistRead
}

const FULL_LIST = [wlEntry(1, 7, 0), wlEntry(2, SHOW_ID, 1), wlEntry(3, 9, 2)]

let onWatchlist = false

const { requests } = startMswServer(
  http.get('/api/shows/:id', () =>
    HttpResponse.json({ id: SHOW_ID, title: 'Example Show', media_type: 'tv', content_type: 'tv' }),
  ),
  http.get('/api/config', () => HttpResponse.json({})),
  http.get('/api/watchlist', ({ request }) => {
    const showId = new URL(request.url).searchParams.get('show_id')
    if (showId !== null) {
      return HttpResponse.json(onWatchlist ? FULL_LIST.filter((e) => e.show_id === Number(showId)) : [])
    }
    return HttpResponse.json(FULL_LIST)
  }),
)

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

const watchlistRequests = () => requests.filter((r) => r.startsWith('GET /api/watchlist'))

describe('useShowDetailData — watchlist membership', () => {
  test('a show not on the watchlist is checked by show_id and the full list is never fetched', async () => {
    onWatchlist = false
    const { result } = renderHook(() => useShowDetailData(SHOW_ID), { wrapper: makeWrapper() })

    await waitFor(() => expect(watchlistRequests()).toEqual([`GET /api/watchlist?show_id=${SHOW_ID}`]))
    await waitFor(() => expect(result.current.show).toBeDefined())

    expect(result.current.watchlistEntry).toBeNull()
    expect(result.current.watchlistEntries).toEqual([])
    expect(requests.some((r) => r.includes('limit=10000'))).toBe(false)
  })

  test('a show on the watchlist exposes its entry, then loads the full list for queue position', async () => {
    onWatchlist = true
    const { result } = renderHook(() => useShowDetailData(SHOW_ID), { wrapper: makeWrapper() })

    await waitFor(() => expect(result.current.watchlistEntry?.id).toBe(2))
    await waitFor(() => expect(result.current.watchlistEntries).toEqual(FULL_LIST))

    expect(watchlistRequests()[0]).toBe(`GET /api/watchlist?show_id=${SHOW_ID}`)
  })
})
