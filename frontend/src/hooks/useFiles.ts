import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import type { FileRead, FileMatchRequest, FileStatus, TmdbSuggestionsResponse } from '@/types/api'

export const fileKeys = {
  all: ['files'] as const,
  list: (status?: FileStatus, page?: number, pageSize?: number, search?: string) =>
    [...fileKeys.all, 'list', status ?? 'all', page ?? 0, pageSize ?? 50, search ?? ''] as const,
  detail: (id: number) => [...fileKeys.all, 'detail', id] as const,
}

export interface FilesPage {
  data: FileRead[]
  total: number
}

export function useFiles({
  status,
  page = 0,
  pageSize = 50,
  search,
}: {
  status?: FileStatus
  page?: number
  pageSize?: number
  search?: string
} = {}) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (search) params.set('search', search)
  params.set('limit', String(pageSize))
  params.set('offset', String(page * pageSize))
  return useQuery({
    queryKey: fileKeys.list(status, page, pageSize, search),
    queryFn: () => api.getWithTotal<FileRead[]>(`/files?${params}`),
  })
}

export function useFilesByShow(showId: number) {
  return useQuery({
    queryKey: [...fileKeys.all, 'show', showId] as const,
    queryFn: () => api.get<FileRead[]>(`/files?show_id=${showId}&limit=1000`),
  })
}

export function useUnmatchedFilesForShow(showId: number) {
  return useQuery({
    queryKey: [...fileKeys.all, 'unmatched-for-show', showId] as const,
    queryFn: () => api.get<FileRead[]>(`/files?status=unmatched&show_id=${showId}&limit=1000`),
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
    mutationFn: ({
      showId,
      episodeId,
      fileId,
    }: {
      showId: number
      episodeId: number
      fileId?: number
    }) => {
      const qs = fileId != null ? `?file_id=${fileId}` : ''
      return api.post<FileRead>(
        `/shows/${showId}/episodes/${episodeId}/begin-rematch${qs}`,
        {},
      )
    },
    onSuccess: (_data, { showId }) => {
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
    },
  })
}

export function useLinkEpisodeFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      showId,
      episodeId,
      path,
    }: {
      showId: number
      episodeId: number
      path: string
    }) => api.post<FileRead>(`/shows/${showId}/episodes/${episodeId}/link-file`, { path }),
    onSuccess: (_data, { showId }) => {
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
      qc.invalidateQueries({ queryKey: fileKeys.all })
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
