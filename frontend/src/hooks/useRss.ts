import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { showKeys } from '@/hooks/useShows'
import { dashboardKeys } from '@/hooks/useDashboard'
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
  RssConfigDiff,
  FeedEntriesRead,
  FeedAddShowRequest,
  FeedAddShowResult,
  FeedRegexSuggestRequest,
  FeedRegexSuggestion,
  FeedRegexTestRequest,
  RegexMatchReportRead,
  TaskRead,
} from '@/types/api'

export const rssKeys = {
  all: ['rss'] as const,
  feeds: () => [...rssKeys.all, 'feeds'] as const,
  subscriptions: (filters?: { show_id?: number; feed_id?: number; enabled_only?: boolean }) =>
    [...rssKeys.all, 'subscriptions', filters ?? {}] as const,
  recommendations: () => [...rssKeys.all, 'recommendations'] as const,
  feedEntries: (feedId: number) => [...rssKeys.all, 'feed-entries', feedId] as const,
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

export function useRssDownload() {
  return useMutation({
    mutationFn: async () => {
      const { blob, filename } = await api.downloadBlob('/rss/download')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    },
  })
}

export function useRssDiff() {
  return useMutation({
    mutationFn: () => api.get<RssConfigDiff>('/rss/diff'),
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

/**
 * Suggest regexes for a subscription. `feedId` is the feed currently selected
 * in the (possibly unsaved) edit form; the backend uses it for hint lookup
 * instead of the persisted feed. `null` means "no feed selected".
 * `mutate(previous)` takes the include regexes already suggested this session;
 * a non-empty list makes the backend skip its cache and produce a different one.
 */
export function useSuggestRegex(subId: number | null, feedId: number | null) {
  return useMutation({
    mutationFn: (previous: string[]) => {
      if (subId == null) return Promise.reject(new Error('No subscription selected'))
      return api.post<RssRegexSuggestion>(`/rss/subscriptions/${subId}/suggest-regex`, {
        feed_id: feedId,
        previous,
      })
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

/**
 * Entries of a feed (fetched server-side), grouped by parsed show name.
 *
 * `retry: false` so a failing tracker is hit once per open, not twice (the
 * global default retries once). Short staleTime mirrors the server's 5-minute
 * entry cache; use `useRefreshFeedEntries` to force a refetch.
 */
export function useFeedEntries(feedId: number | null) {
  return useQuery({
    queryKey: rssKeys.feedEntries(feedId ?? -1),
    queryFn: () => api.get<FeedEntriesRead>(`/rss/feeds/${feedId}/entries`),
    enabled: feedId != null,
    retry: false,
    staleTime: 5 * 60_000,
  })
}

export function useRefreshFeedEntries(feedId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.get<FeedEntriesRead>(`/rss/feeds/${feedId}/entries?refresh=true`),
    onSuccess: (data) => {
      qc.setQueryData(rssKeys.feedEntries(feedId), data)
    },
  })
}

/**
 * LLM regex suggestion for a feed group that has no subscription yet. The
 * server re-reads the group's real release titles, so the client sends only
 * the group key (`parsed_name`), the picked show title, and prior suggestions.
 */
export function useSuggestFeedRegex(feedId: number) {
  return useMutation({
    mutationFn: (body: FeedRegexSuggestRequest) =>
      api.post<FeedRegexSuggestion>(`/rss/feeds/${feedId}/suggest-regex`, body),
  })
}

/** Preview which of a feed group's current titles a hand-edited filter selects. */
export function useTestFeedRegex(feedId: number) {
  return useMutation({
    mutationFn: (body: FeedRegexTestRequest) =>
      api.post<RegexMatchReportRead>(`/rss/feeds/${feedId}/test-regex`, body),
  })
}

/**
 * Add a feed group's show to the library (or reuse one) and create its
 * subscription in one step. Invalidates the feed's entry groups so the group
 * flips to "Subscribed", plus subscriptions, shows and the dashboard.
 */
export function useAddShowFromFeed(feedId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: FeedAddShowRequest) =>
      api.post<FeedAddShowResult>(`/rss/feeds/${feedId}/add-show`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: rssKeys.feedEntries(feedId) })
      qc.invalidateQueries({ queryKey: rssKeys.subscriptions() })
      qc.invalidateQueries({ queryKey: showKeys.all })
      qc.invalidateQueries({ queryKey: dashboardKeys.all })
    },
  })
}
