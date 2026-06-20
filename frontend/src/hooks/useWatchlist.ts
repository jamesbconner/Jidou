import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { WatchlistCreate, WatchlistList, WatchlistRead, WatchlistStatus, WatchlistUpdate } from '@/types/api'

export const watchlistKeys = {
  all: ['watchlist'] as const,
  list: (status?: WatchlistStatus) => [...watchlistKeys.all, 'list', status ?? 'all'] as const,
  detail: (id: number) => [...watchlistKeys.all, 'detail', id] as const,
}

export function useWatchlist(status?: WatchlistStatus) {
  const params = status ? `?status=${status}` : ''
  return useQuery({
    queryKey: watchlistKeys.list(status),
    queryFn: () => api.get<WatchlistList[]>(`/watchlist${params}`),
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
