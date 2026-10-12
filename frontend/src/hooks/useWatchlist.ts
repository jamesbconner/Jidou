import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { WatchlistCreate, WatchlistRead, WatchlistStatus, WatchlistUpdate } from '@/types/api'

export const watchlistKeys = {
  all: ['watchlist'] as const,
  list: (status?: WatchlistStatus, limit?: number) =>
    [...watchlistKeys.all, 'list', status ?? 'all', limit ?? 50] as const,
  detail: (id: number) => [...watchlistKeys.all, 'detail', id] as const,
  byShow: (showId: number) => [...watchlistKeys.all, 'show', showId] as const,
}

export function useWatchlist(
  status?: WatchlistStatus,
  limit = 50,
  opts: { enabled?: boolean } = {},
) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('limit', String(limit))
  return useQuery({
    queryKey: watchlistKeys.list(status, limit),
    queryFn: () => api.get<WatchlistRead[]>(`/watchlist?${params}`),
    enabled: opts.enabled ?? true,
  })
}

/**
 * The watchlist entry for one show, or `null` when it is not on the watchlist.
 *
 * Uses `GET /watchlist?show_id=` (at most one row, as a show is on the
 * watchlist at most once) so a page can check membership without fetching
 * the whole watchlist.
 */
export function useWatchlistEntryForShow(showId: number) {
  return useQuery({
    queryKey: watchlistKeys.byShow(showId),
    queryFn: () => api.get<WatchlistRead[]>(`/watchlist?show_id=${showId}`),
    select: (entries) => entries[0] ?? null,
    enabled: Number.isFinite(showId),
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
    mutationFn: (items: WatchlistRead[]) =>
      api.post<void>(
        '/watchlist/reorder',
        items.map((item, i) => ({ id: item.id, position: i + 1 })),
      ),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}
