import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { RecentEpisodeItem, RecentShowItem } from '@/types/api'

export type RecentSort = 'tracked' | 'release'

export const RECENT_SORT_LABELS: Record<RecentSort, string> = {
  tracked: 'Recently Tracked',
  release: 'Recently Released',
}

export interface RecentQueryParams {
  sort: RecentSort
  contentType: string
  genre: string
  limit: number
}

export const dashboardKeys = {
  all: ['dashboard'] as const,
  recentShows: (params: RecentQueryParams) => [...dashboardKeys.all, 'recent-shows', params] as const,
  recentEpisodes: (params: RecentQueryParams) =>
    [...dashboardKeys.all, 'recent-episodes', params] as const,
  genres: () => [...dashboardKeys.all, 'genres'] as const,
}

function buildQuery(params: RecentQueryParams): string {
  const search = new URLSearchParams({ sort: params.sort, limit: String(params.limit) })
  if (params.contentType) search.set('content_type', params.contentType)
  if (params.genre) search.set('genre', params.genre)
  return search.toString()
}

export function useRecentShows(params: RecentQueryParams) {
  return useQuery({
    queryKey: dashboardKeys.recentShows(params),
    queryFn: () => api.get<RecentShowItem[]>(`/dashboard/recent-shows?${buildQuery(params)}`),
  })
}

export function useRecentEpisodes(params: RecentQueryParams) {
  return useQuery({
    queryKey: dashboardKeys.recentEpisodes(params),
    queryFn: () => api.get<RecentEpisodeItem[]>(`/dashboard/recent-episodes?${buildQuery(params)}`),
  })
}

export function useDashboardGenres() {
  return useQuery({
    queryKey: dashboardKeys.genres(),
    queryFn: () => api.get<string[]>('/dashboard/genres'),
    staleTime: 60_000,
  })
}
