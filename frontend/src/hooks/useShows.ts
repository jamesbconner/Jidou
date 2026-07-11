import { useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ShowList, ShowRead, ShowCreate, ShowPatch, ShowPaths, EpisodeList, TmdbSearchResponse } from '@/types/api'

export type ShowSortOrder =
  | 'title_asc'
  | 'title_desc'
  | 'added_desc'
  | 'added_asc'
  | 'release_desc'
  | 'release_asc'
  | 'last_aired_desc'
  | 'rating_desc'
  | 'episodes_desc'

export const SHOW_SORT_LABELS: Record<ShowSortOrder, string> = {
  title_asc: 'Title A → Z',
  title_desc: 'Title Z → A',
  added_desc: 'Recently Added',
  added_asc: 'Oldest Added',
  release_desc: 'Newest Release',
  release_asc: 'Oldest Release',
  last_aired_desc: 'Recently Aired',
  rating_desc: 'Highest Rated',
  episodes_desc: 'Most Episodes',
}

export const showKeys = {
  all: ['shows'] as const,
  list: (sort?: ShowSortOrder, limit?: number) =>
    [...showKeys.all, 'list', sort ?? 'title_asc', limit ?? 500] as const,
  detail: (id: number) => [...showKeys.all, 'detail', id] as const,
  episodes: (id: number) => [...showKeys.all, 'episodes', id] as const,
  trending: () => ['tmdb', 'trending'] as const,
  search: (q: string, mediaType?: string) => ['tmdb', 'search', q, mediaType ?? null] as const,
}

export function useShows(sort: ShowSortOrder = 'title_asc', limit = 500) {
  return useQuery({
    queryKey: showKeys.list(sort, limit),
    queryFn: () => api.get<ShowList[]>(`/shows?sort=${sort}&limit=${limit}`),
  })
}

export function useShow(id: number) {
  return useQuery({
    queryKey: showKeys.detail(id),
    queryFn: () => api.get<ShowRead>(`/shows/${id}`),
  })
}

export function useShowEpisodes(showId: number) {
  return useQuery({
    queryKey: showKeys.episodes(showId),
    queryFn: () => api.get<EpisodeList[]>(`/shows/${showId}/episodes`),
  })
}

export function useTrendingShows(mediaType = 'tv') {
  return useQuery({
    queryKey: showKeys.trending(),
    queryFn: () => api.get<TmdbSearchResponse>(`/shows/trending?media_type=${mediaType}`),
  })
}

export function useSearchShows(query: string, mediaType?: string) {
  return useQuery({
    queryKey: showKeys.search(query, mediaType),
    queryFn: () =>
      api.get<TmdbSearchResponse>(
        `/shows/search?query=${encodeURIComponent(query)}${mediaType ? `&media_type=${mediaType}` : ''}`,
      ),
    enabled: query.length >= 2,
  })
}

/**
 * Map of `${tmdb_id}:${media_type}` -> Show for every show already in the
 * library.
 *
 * The DB enforces uniqueness on tmdb_id alone (no media_type column in the
 * constraint), so Jidou's own show list can never contain two rows sharing a
 * tmdb_id. But a TMDB *search result* spans TMDB's full catalog, where a tv
 * item and a movie item legitimately share the same raw numeric id -- TMDB
 * uses separate id namespaces per media type. Comparing a search result
 * against the library by tmdb_id alone can therefore match the wrong
 * already-tracked show (e.g. a tv show and an unrelated movie that happen to
 * share a numeric id). Keying by `tmdb_id:media_type` avoids that collision
 * when cross-referencing search results against the library.
 */
export function useLibraryIndex() {
  const { data: allShows = [] } = useShows('title_asc', 10000)
  return useMemo(
    () => new Map(allShows.map((s) => [`${s.tmdb_id}:${s.media_type}`, s])),
    [allShows],
  )
}

export function useCreateShow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: ShowCreate) => api.post<ShowRead>('/shows', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: showKeys.all }),
  })
}

export function useUpdateShowPaths(showId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (paths: ShowPaths) => api.put<ShowRead>(`/shows/${showId}/paths`, paths),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.detail(showId) })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}

export function useDeleteShow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/shows/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: showKeys.all }),
  })
}

export function useSyncEpisodes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (showId: number) => api.post<EpisodeList[]>(`/shows/${showId}/sync-episodes`),
    onSuccess: (_data, showId) => {
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}

export function usePatchShow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: ShowPatch }) =>
      api.patch<ShowRead>(`/shows/${id}`, patch),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: showKeys.detail(id) })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}

export function useRematchShow(showId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ tmdbId, mediaType }: { tmdbId: number; mediaType: string }) =>
      api.post<ShowRead>(`/shows/${showId}/rematch`, { tmdb_id: tmdbId, media_type: mediaType }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.detail(showId) })
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
      qc.invalidateQueries({ queryKey: showKeys.all })
    },
  })
}

export function useUpdateShowAliases(showId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (aliases: string[]) =>
      api.put<ShowRead>(`/shows/${showId}/aliases`, { aliases }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.detail(showId) })
    },
  })
}

export function useRegenerateShowAliases(showId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<ShowRead>(`/shows/${showId}/aliases/regenerate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.detail(showId) })
    },
  })
}

export function useAssignImportEpisode() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      showId,
      episodeId,
      filename,
    }: {
      showId: number
      episodeId: number
      filename: string
    }) => api.post(`/shows/${showId}/episodes/${episodeId}/assign-import`, { filename }),
    onSuccess: (_data, { showId }) => {
      qc.invalidateQueries({ queryKey: showKeys.episodes(showId) })
    },
  })
}
