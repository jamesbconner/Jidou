import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import type { FileRead, FileMatchRequest, FileStatus, TmdbSuggestionsResponse } from '@/types/api'

export const fileKeys = {
  all: ['files'] as const,
  list: (status?: FileStatus) => [...fileKeys.all, 'list', status ?? 'all'] as const,
  detail: (id: number) => [...fileKeys.all, 'detail', id] as const,
}

export function useFiles(status?: FileStatus) {
  const params = status ? `?status=${status}` : ''
  return useQuery({
    queryKey: fileKeys.list(status),
    queryFn: () => api.get<FileRead[]>(`/files${params}`),
  })
}

export function useFilesByShow(showId: number) {
  return useQuery({
    queryKey: [...fileKeys.all, 'show', showId] as const,
    queryFn: () => api.get<FileRead[]>(`/files?show_id=${showId}&limit=1000`),
  })
}

export function useFile(id: number) {
  return useQuery({
    queryKey: fileKeys.detail(id),
    queryFn: () => api.get<FileRead>(`/files/${id}`),
  })
}

export function useRematchFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: FileMatchRequest }) =>
      api.post<FileRead>(`/files/${id}/match`, payload),
    onSuccess: (data) => {
      qc.setQueryData(fileKeys.detail(data.id), data)
      qc.invalidateQueries({ queryKey: fileKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}

export function useBeginEpisodeRematch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ showId, episodeId }: { showId: number; episodeId: number }) =>
      api.post<FileRead>(`/shows/${showId}/episodes/${episodeId}/begin-rematch`, {}),
    onSuccess: (_data, { showId }) => {
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
    },
  })
}

export function useTmdbSuggestions(fileId: number | null) {
  return useQuery({
    queryKey: [...fileKeys.all, 'tmdb-suggestions', fileId] as const,
    queryFn: () => api.get<TmdbSuggestionsResponse>(`/files/${fileId}/tmdb-suggestions`),
    enabled: fileId != null,
    staleTime: 5 * 60 * 1000,
  })
}
