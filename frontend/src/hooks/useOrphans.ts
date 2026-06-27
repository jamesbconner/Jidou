import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import type { OrphanedTrackingRecord } from '@/types/api'

export const orphanKeys = {
  all: ['orphans'] as const,
  list: () => [...orphanKeys.all, 'list'] as const,
  forShow: (showId: number) => [...orphanKeys.all, 'show', showId] as const,
}

export function useOrphans() {
  return useQuery({
    queryKey: orphanKeys.list(),
    queryFn: () => api.get<OrphanedTrackingRecord[]>('/orphans'),
  })
}

export function useOrphansForShow(showId: number) {
  return useQuery({
    queryKey: orphanKeys.forShow(showId),
    queryFn: () => api.get<OrphanedTrackingRecord[]>(`/orphans/show/${showId}`),
  })
}

export function useDismissOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (orphanId: number) => api.delete<void>(`/orphans/${orphanId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: orphanKeys.all }),
  })
}

export function useResolveOrphan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ orphanId, episodeId }: { orphanId: number; episodeId: number }) =>
      api.post<void>(`/orphans/${orphanId}/resolve`, { episode_id: episodeId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: orphanKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}
