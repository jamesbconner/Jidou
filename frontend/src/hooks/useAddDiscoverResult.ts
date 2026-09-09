import { useCallback, useState } from 'react'
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
  // Pull out the stable `mutateAsync` refs rather than the mutation objects
  // (which get a new identity on every state change) so `add` below can be a
  // stable useCallback — consumers memoize their card lists on it, and an
  // unstable `add` would reset the Similar Titles carousel's scroll on every
  // parent re-render.
  const { mutateAsync: createShow } = useCreateShow()
  const { mutateAsync: createWatchlistEntry } = useCreateWatchlistEntry()
  const { mutateAsync: ensureRssStub } = useEnsureRssStub()

  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set())
  const [issueKeys, setIssueKeys] = useState<Map<string, AddIssue>>(new Map())

  const add = useCallback(async (result: DiscoverResult) => {
    const key = resultKey(result)
    setPendingKeys((prev) => new Set(prev).add(key))
    setIssueKeys((prev) => {
      const next = new Map(prev)
      next.delete(key)
      return next
    })
    try {
      const show = await createShow(buildShowCreatePayload(result))
      const [watchlistResult, rssResult] = await Promise.allSettled([
        createWatchlistEntry({ show_id: show.id }),
        ensureRssStub(show.id),
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
  }, [createShow, createWatchlistEntry, ensureRssStub])

  return { add, pendingKeys, issueKeys }
}
