import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type {
  AdminStats,
  FileTimelineEntry,
  PipelineStatusEntry,
  RecentEpisodeItem,
  RecentShowItem,
} from '@/types/api'

export type RecentSort = 'tracked' | 'release'

export const RECENT_SORT_LABELS: Record<RecentSort, string> = {
  tracked: 'Recently Tracked',
  release: 'Recently Released',
}

export interface RecentQueryParams {
  sort: RecentSort
  // Omitted entirely by callers scoped to a single content type already
  // (e.g. the movies carousel, where it'd always be redundant).
  contentType?: string
  genre: string
  limit: number
}

export const dashboardKeys = {
  all: ['dashboard'] as const,
  recentShows: (params: RecentQueryParams) => [...dashboardKeys.all, 'recent-shows', params] as const,
  recentMovies: (params: RecentQueryParams) =>
    [...dashboardKeys.all, 'recent-movies', params] as const,
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

export function useRecentMovies(params: RecentQueryParams) {
  return useQuery({
    queryKey: dashboardKeys.recentMovies(params),
    queryFn: () => api.get<RecentShowItem[]>(`/dashboard/recent-movies?${buildQuery(params)}`),
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

/**
 * Headline library counts for the Dashboard. Polled every 30 s so the numbers
 * track a running scan without a manual refresh.
 */
export function useAdminStats() {
  return useQuery({
    queryKey: ['admin', 'stats'] as const,
    queryFn: () => api.get<AdminStats>('/admin/stats'),
    refetchInterval: 30_000,
  })
}

/** Files-per-day series behind the Dashboard's activity bar chart. */
export function useFilesTimeline() {
  return useQuery({
    queryKey: ['admin', 'stats', 'files-timeline'] as const,
    queryFn: () => api.get<FileTimelineEntry[]>('/admin/stats/files-timeline'),
    refetchInterval: 60_000,
  })
}

/** File counts per pipeline status, for the Dashboard's status pie chart. */
export function usePipelineStatus() {
  return useQuery({
    queryKey: ['admin', 'stats', 'pipeline-status'] as const,
    queryFn: () => api.get<PipelineStatusEntry[]>('/admin/stats/pipeline-status'),
    refetchInterval: 30_000,
  })
}
