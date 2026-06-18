import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ShowList, ShowRead, ShowCreate, ShowPaths, EpisodeList, TmdbSearchResponse } from '@/types/api'

export const showKeys = {
  all: ['shows'] as const,
  list: () => [...showKeys.all, 'list'] as const,
  detail: (id: number) => [...showKeys.all, 'detail', id] as const,
  episodes: (id: number) => [...showKeys.all, 'episodes', id] as const,
  trending: () => ['tmdb', 'trending'] as const,
  search: (q: string) => ['tmdb', 'search', q] as const,
}

export function useShows() {
  return useQuery({
    queryKey: showKeys.list(),
    queryFn: () => api.get<ShowList[]>('/shows'),
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

export function useSearchShows(query: string) {
  return useQuery({
    queryKey: showKeys.search(query),
    queryFn: () => api.get<TmdbSearchResponse>(`/shows/search?query=${encodeURIComponent(query)}`),
    enabled: query.length >= 2,
  })
}

export function useCreateShow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: ShowCreate) => api.post<ShowRead>('/shows', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: showKeys.list() }),
  })
}

export function useUpdateShowPaths(showId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (paths: ShowPaths) => api.put<ShowRead>(`/shows/${showId}/paths`, paths),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: showKeys.detail(showId) })
      qc.invalidateQueries({ queryKey: showKeys.list() })
    },
  })
}

export function useDeleteShow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/shows/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: showKeys.list() }),
  })
}
