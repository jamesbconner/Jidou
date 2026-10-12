import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import { invalidateShowsAndFiles } from '@/hooks/invalidation'
import type { FileRead, FileMatchRequest, FileStatus, TmdbSuggestionsResponse } from '@/types/api'

interface FilesListParams {
  status?: FileStatus
  limit: number
  offset: number
  search?: string
  showIgnored?: boolean
  /** Only files flagged as a duplicate of an earlier file for the same episode. */
  duplicatesOnly?: boolean
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
      params.duplicatesOnly ?? false,
    ] as const,
  detail: (id: number) => [...fileKeys.all, 'detail', id] as const,
}

export interface FilesPage {
  data: FileRead[]
  total: number
}

export function useFiles(params: FilesListParams) {
  const { status, limit, offset, search, showIgnored = false, duplicatesOnly = false } = params
  const qs = new URLSearchParams()
  if (status) qs.set('status', status)
  if (search) qs.set('search', search)
  if (showIgnored) qs.set('show_ignored', 'true')
  if (duplicatesOnly) qs.set('duplicates_only', 'true')
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
      invalidateShowsAndFiles(qc)
    },
  })
}

/**
 * Reassign a file to a different show (or detach it with `null`) from the
 * Files table. Owns its cache refresh so the page never touches the query
 * client.
 */
export function useAssignFileShow(fileId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (newShowId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, { show_id: newShowId }),
    onSuccess: () => {
      invalidateShowsAndFiles(qc)
    },
  })
}

/**
 * Reassign a file to a different episode (or clear it with `null`) from the
 * Files table. The cached list rows are patched in place first so the row
 * does not flicker back to its old episode while the refetch is in flight.
 * `onSuccess` / `onError` let the row component reset its local edit state.
 */
export function useAssignFileEpisode(
  fileId: number,
  callbacks: { onSuccess?: () => void; onError?: (err: unknown) => void } = {},
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (newEpisodeId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, {
        episode_id: newEpisodeId,
        ...(newEpisodeId !== null ? { status: 'matched', error_message: null } : {}),
      }),
    onSuccess: (updated) => {
      callbacks.onSuccess?.()
      qc.setQueriesData<FilesPage>({ queryKey: [...fileKeys.all, 'list'] }, (old) =>
        old
          ? { ...old, data: old.data.map((f) => (f.id === updated.id ? { ...f, ...updated } : f)) }
          : old,
      )
      invalidateShowsAndFiles(qc)
    },
    onError: (err: unknown) => callbacks.onError?.(err),
  })
}

/**
 * Attach an existing, unlinked file to an episode (LinkFileModal's "pick an
 * existing file" mode).
 */
export function useLinkExistingFile(episodeId: number, callbacks: { onSuccess?: () => void } = {}) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: number) =>
      api.patch<FileRead>(`/files/${fileId}`, {
        episode_id: episodeId,
        status: 'matched',
        error_message: null,
      }),
    onSuccess: () => {
      invalidateShowsAndFiles(qc)
      callbacks.onSuccess?.()
    },
  })
}

/**
 * Set or clear the episode a file is assigned to (FixEpisodeModal). Clearing
 * also resets the status to `unmatched` so the file re-enters the queue.
 */
export function useFixFileEpisode(fileId: number, callbacks: { onSuccess?: () => void } = {}) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (episodeId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, {
        episode_id: episodeId,
        ...(episodeId !== null
          ? { status: 'matched', error_message: null }
          : { status: 'unmatched' }),
      }),
    onSuccess: () => {
      invalidateShowsAndFiles(qc)
      callbacks.onSuccess?.()
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
      replace,
    }: {
      showId: number
      episodeId: number
      path: string
      replace?: boolean
    }) =>
      api.post<FileRead>(`/shows/${showId}/episodes/${episodeId}/link-file`, {
        path,
        ...(replace ? { replace: true } : {}),
      }),
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
      invalidateShowsAndFiles(qc)
    },
  })
}

/**
 * Checks which of the given candidate paths still exist on disk — used to
 * filter stale entries (renamed/moved/deleted outside the app) out of
 * "pick existing file" pickers before a Scan Local Files reconciliation
 * pass has had a chance to catch up.
 */
export function useVerifyPaths(paths: string[]) {
  return useQuery({
    queryKey: [...fileKeys.all, 'verify-paths', ...paths] as const,
    queryFn: () => api.post<{ existing: string[] }>('/files/verify-paths', { paths }),
    enabled: paths.length > 0,
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
