import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import type { FileRead, FileMatchRequest, FileStatus, TmdbSuggestionsResponse } from '@/types/api'

interface FilesListParams {
  status?: FileStatus
  limit: number
  offset: number
  search?: string
  showIgnored?: boolean
}

export const fileKeys = {
  all: ['files'] as const,
  list: (params: FilesListParams) =>
    [
      ...fileKeys.all,
      'list',
      params.status ?? 'all',
      params.limit,
      params.offset,
      params.search ?? '',
      params.showIgnored ?? false,
    ] as const,
  detail: (id: number) => [...fileKeys.all, 'detail', id] as const,
}

export interface FilesPage {
  data: FileRead[]
  total: number
}

export function useFiles(params: FilesListParams) {
  const { status, limit, offset, search, showIgnored = false } = params
  const qs = new URLSearchParams()
  if (status) qs.set('status', status)
  if (search) qs.set('search', search)
  if (showIgnored) qs.set('show_ignored', 'true')
  qs.set('limit', String(limit))
  qs.set('offset', String(offset))
  return useQuery({
    queryKey: fileKeys.list(params),
    queryFn: () => api.getWithTotal<FileRead[]>(`/files?${qs}`),
  })
}

export function useFilesByShow(showId: number, enabled = true) {
  return useQuery({
    queryKey: [...fileKeys.all, 'show', showId] as const,
    // show_ignored=true: this is a show-scoped listing (e.g. Show Detail), not
    // the triage Files page, so ignored files linked to the show must still
    // appear rather than silently vanishing under the new default exclusion.
    queryFn: () => api.get<FileRead[]>(`/files?show_id=${showId}&show_ignored=true&limit=1000`),
    enabled,
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

export function useLinkMovieFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      showId,
      path,
      replace,
    }: {
      showId: number
      path: string
      /** Unlink the movie's existing file first instead of 422ing. */
      replace?: boolean
    }) => api.post<FileRead>(`/shows/${showId}/link-movie-file`, { path, replace }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.all })
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
