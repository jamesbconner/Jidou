import { useState } from 'react'
import { useCreateShow } from '@/hooks/useShows'
import { useCreateWatchlistEntry } from '@/hooks/useWatchlist'
import { useEnsureRssStub } from '@/hooks/useRss'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import type { DiscoverResult } from '@/types/api'

/**
 * Per-result outcome when an "Add + Watchlist" attempt didn't fully succeed.
 *
 * - `failed` — show creation itself threw; nothing was added.
 * - `partial` — the show was created, but the follow-up watchlist entry and/or
 *   RSS stub didn't. `Promise.allSettled` never rejects, so this is detected by
 *   inspecting each settled result; `message` names which steps went through.
 */
export type AddIssue = { kind: 'failed' } | { kind: 'partial'; message: string }

/** Stable per-result key: TMDB ids collide across media types, so include it. */
export function resultKey(result: Pick<DiscoverResult, 'id' | 'media_type'>): string {
  return `${result.id}:${result.media_type}`
}

/**
 * Shared "Add + Watchlist" flow for TMDB discover / similar-title results.
 *
 * Creates the show, then best-effort adds a watchlist entry and an RSS stub,
 * tracking per-result pending and partial/failed state keyed by
 * `${id}:${media_type}`. Used by both the Discover page and the show detail
 * page's "Similar Titles" carousel so the two stay in lockstep.
 */
export function useAddDiscoverResult() {
  const createShow = useCreateShow()
  const createWatchlistEntry = useCreateWatchlistEntry()
  const ensureRssStub = useEnsureRssStub()

  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set())
  const [issueKeys, setIssueKeys] = useState<Map<string, AddIssue>>(new Map())

  async function add(result: DiscoverResult) {
    const key = resultKey(result)
    setPendingKeys((prev) => new Set(prev).add(key))
    setIssueKeys((prev) => {
      const next = new Map(prev)
      next.delete(key)
      return next
    })
    try {
      const show = await createShow.mutateAsync(buildShowCreatePayload(result))
      const [watchlistResult, rssResult] = await Promise.allSettled([
        createWatchlistEntry.mutateAsync({ show_id: show.id }),
        ensureRssStub.mutateAsync(show.id),
      ])
      const watchlistFailed = watchlistResult.status === 'rejected'
      const rssFailed = rssResult.status === 'rejected'
      if (watchlistFailed && rssFailed) {
        setIssueKeys((prev) =>
          new Map(prev).set(key, {
            kind: 'partial',
            message: 'Added to library, but watchlist and RSS stub setup both failed.',
          }),
        )
      } else if (watchlistFailed) {
        setIssueKeys((prev) =>
          new Map(prev).set(key, {
            kind: 'partial',
            message: 'Added to library, but watchlist setup failed.',
          }),
        )
      } else if (rssFailed) {
        setIssueKeys((prev) =>
          new Map(prev).set(key, {
            kind: 'partial',
            message: 'Added to library and watchlist, but RSS stub creation failed.',
          }),
        )
      }
    } catch {
      setIssueKeys((prev) => new Map(prev).set(key, { kind: 'failed' }))
    } finally {
      setPendingKeys((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }

  return { add, pendingKeys, issueKeys }
}
