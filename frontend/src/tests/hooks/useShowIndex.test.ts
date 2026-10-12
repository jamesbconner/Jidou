import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect } from 'vitest'
import { createElement } from 'react'
import { http, HttpResponse } from 'msw'
import { useLibraryIndex, useShowIndex } from '@/hooks/useShows'
import type { ShowIndexEntry } from '@/types/api'
import { startMswServer } from '@/tests/helpers/msw'

// DF-18: pickers and library lookups read the lightweight GET /shows/index
// instead of fetching the full /shows list with limit=10000.

const INDEX: ShowIndexEntry[] = [
  {
    id: 1,
    tmdb_id: 1396,
    title: 'Example Drama',
    sys_name: 'Example Drama',
    aliases: ['Drama'],
    media_type: 'tv',
    content_type: 'tv',
    local_path: '/media/tv/Example Drama',
  },
  {
    id: 2,
    tmdb_id: 1396,
    title: 'Example Film',
    sys_name: null,
    aliases: null,
    media_type: 'movie',
    content_type: null,
    local_path: null,
  },
]

const { requests } = startMswServer(http.get('/api/shows/index', () => HttpResponse.json(INDEX)))

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

describe('useShowIndex', () => {
  test('reads GET /shows/index and keeps the server order', async () => {
    const { result } = renderHook(() => useShowIndex(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(result.current.data).toEqual(INDEX)
    expect(requests).toEqual(['GET /api/shows/index'])
  })
})

describe('useLibraryIndex', () => {
  test('keys the index by tmdb_id:media_type from /shows/index, never the full list', async () => {
    const { result } = renderHook(() => useLibraryIndex(), { wrapper: makeWrapper() })
    await waitFor(() => expect(result.current.size).toBe(2))

    expect(result.current.get('1396:tv')).toEqual(INDEX[0])
    expect(result.current.get('1396:movie')).toEqual(INDEX[1])
    // local_path survives, so the rematch/resolve modals can still tell
    // whether an already-tracked show has a folder to reuse.
    expect(result.current.get('1396:tv')?.local_path).toBe('/media/tv/Example Drama')
    expect(requests).toEqual(['GET /api/shows/index'])
    expect(requests.some((r) => r.includes('limit=10000'))).toBe(false)
  })
})
