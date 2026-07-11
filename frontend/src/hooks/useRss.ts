import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type {
  RssFeedRead,
  RssFeedCreate,
  RssFeedUpdate,
  RssSubscriptionRead,
  RssSubscriptionCreate,
  RssSubscriptionUpdate,
  RssSubscriptionRecommendation,
  RssSubscriptionBulkPatchItem,
  RssRegexSuggestion,
  TaskRead,
} from '@/types/api'

export const rssKeys = {
  all: ['rss'] as const,
  feeds: () => [...rssKeys.all, 'feeds'] as const,
  subscriptions: (filters?: { show_id?: number; feed_id?: number; enabled_only?: boolean }) =>
    [...rssKeys.all, 'subscriptions', filters ?? {}] as const,
  recommendations: () => [...rssKeys.all, 'recommendations'] as const,
}

export function useRssFeeds() {
  return useQuery({
    queryKey: rssKeys.feeds(),
    queryFn: () => api.get<RssFeedRead[]>('/rss/feeds'),
  })
}

export function useRssSubscriptions(filters?: {
  show_id?: number
  feed_id?: number
  enabled_only?: boolean
}) {
  const params = new URLSearchParams()
  if (filters?.show_id != null) params.set('show_id', String(filters.show_id))
  if (filters?.feed_id != null) params.set('feed_id', String(filters.feed_id))
  if (filters?.enabled_only) params.set('enabled_only', 'true')
  const qs = params.toString()

  return useQuery({
    queryKey: rssKeys.subscriptions(filters),
    queryFn: () => api.get<RssSubscriptionRead[]>(`/rss/subscriptions${qs ? `?${qs}` : ''}`),
  })
}

export function useCreateRssSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RssSubscriptionCreate) =>
      api.post<RssSubscriptionRead>('/rss/subscriptions', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.subscriptions() })
    },
  })
}

export function useEnsureRssStub() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (showId: number) =>
      api.post<RssSubscriptionRead>(`/shows/${showId}/rss-stub`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.all })
    },
  })
}

export function usePatchRssSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, update }: { id: number; update: RssSubscriptionUpdate }) =>
      api.patch<RssSubscriptionRead>(`/rss/subscriptions/${id}`, update),
    onSuccess: (updated) => {
      qc.setQueriesData<RssSubscriptionRead[]>(
        { queryKey: rssKeys.subscriptions() },
        (old) => old?.map((s) => (s.id === updated.id ? updated : s)),
      )
      qc.invalidateQueries({ queryKey: rssKeys.subscriptions() })
    },
  })
}

export function useDeleteRssSubscription() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/rss/subscriptions/${id}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: rssKeys.subscriptions() })
    },
  })
}

export function useCreateRssFeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: RssFeedCreate) => api.post<RssFeedRead>('/rss/feeds', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.feeds() })
    },
  })
}

export function usePatchRssFeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, update }: { id: number; update: RssFeedUpdate }) =>
      api.patch<RssFeedRead>(`/rss/feeds/${id}`, update),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.feeds() })
    },
  })
}

export function useDeleteRssFeed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.delete<void>(`/rss/feeds/${id}`),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: rssKeys.feeds() })
    },
  })
}

export function useTriggerRssImport(dryRun = false) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<TaskRead>(`/rss/import?dry_run=${dryRun}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
      qc.invalidateQueries({ queryKey: rssKeys.all })
    },
  })
}

export function useTriggerRssPublish(dryRun = false) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<TaskRead>(`/rss/publish?dry_run=${dryRun}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] })
    },
  })
}

export function useRssRecommendations() {
  return useQuery({
    queryKey: rssKeys.recommendations(),
    queryFn: () => api.get<RssSubscriptionRecommendation[]>('/rss/subscriptions/recommendations'),
  })
}

export function useBulkPatchRssSubscriptions() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (items: RssSubscriptionBulkPatchItem[]) =>
      api.patch<RssSubscriptionRead[]>('/rss/subscriptions/bulk', items),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.subscriptions() })
      qc.invalidateQueries({ queryKey: rssKeys.recommendations() })
    },
  })
}

export function useSuggestRegex(subId: number | null) {
  return useMutation({
    mutationFn: () => {
      if (subId == null) return Promise.reject(new Error('No subscription selected'))
      return api.post<RssRegexSuggestion>(`/rss/subscriptions/${subId}/suggest-regex`)
    },
  })
}

export function useSubscriptionPreview(subId: number | null) {
  return useQuery({
    queryKey: [...rssKeys.all, 'preview', subId] as const,
    queryFn: () => api.get<Record<string, unknown>>(`/rss/subscriptions/${subId}/preview`),
    enabled: subId != null,
  })
}
