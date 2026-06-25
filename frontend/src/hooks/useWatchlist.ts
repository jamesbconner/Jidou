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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: watchlistKeys.all })
    },
  })
}
