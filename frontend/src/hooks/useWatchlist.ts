import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { WatchlistCreate, WatchlistRead, WatchlistStatus, WatchlistUpdate } from '@/types/api'

export const watchlistKeys = {
  all: ['watchlist'] as const,
  list: (status?: WatchlistStatus, limit?: number) =>
    [...watchlistKeys.all, 'list', status ?? 'all', limit ?? 50] as const,
  detail: (id: number) => [...watchlistKeys.all, 'detail', id] as const,
}

export function useWatchlist(status?: WatchlistStatus, limit = 50) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('limit', String(limit))
  return useQuery({
    queryKey: watchlistKeys.list(status, limit),
    queryFn: () => api.get<WatchlistRead[]>(`/watchlist?${params}`),
  })
}

export function useCreateWatchlistEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: WatchlistCreate) => api.post<WatchlistRead>('/watchlist', payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}

export function usePatchWatchlistEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, update }: { id: number; update: WatchlistUpdate }) =>
      api.patch<WatchlistRead>(`/watchlist/${id}`, update),
    onSuccess: (data) => {
      qc.setQueryData(watchlistKeys.detail(data.id), data)
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}

export function useDeleteWatchlistEntry() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/watchlist/${id}`),
    onSettled: () => {
      // Invalidate on both success and error so stale "on watchlist" state
      // clears if the entry was already removed on another client or tab.
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}

export function useReorderWatchlist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (items: WatchlistRead[]) => {
      // Always PATCH every entry with its new 1-based position. Skipping entries
      // whose item.position matches the new index is unsafe: orderedEntries carries
      // stale position values until the post-drag refetch settles, so a second drag
      // before that refetch can produce indices that match the stale values and
      // silently skip all PATCHes while the server keeps the wrong order.
      const results = await Promise.allSettled(
        items.map((item, i) =>
          api.patch<WatchlistRead>(`/watchlist/${item.id}`, { position: i + 1 }),
        ),
      )
      const failures = results.filter((r) => r.status === 'rejected')
      if (failures.length > 0) throw new Error(`${failures.length} position update(s) failed`)
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}
