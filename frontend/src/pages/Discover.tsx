import { useState } from 'react'
import { useDiscoverShows, useLibraryIndex, useCreateShow } from '@/hooks/useShows'
import { useCreateWatchlistEntry } from '@/hooks/useWatchlist'
import { useEnsureRssStub } from '@/hooks/useRss'
import { TmdbResultCard } from '@/components/TmdbResultCard'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import type { DiscoverResult } from '@/types/api'

function subtitleFor(result: DiscoverResult): string {
  if (result.seeded_from.length === 0) return 'Trending'
  if (result.seeded_from.length === 1) return `Because you watch ${result.seeded_from[0]}`
  return `Because you watch ${result.seeded_from[0]} +${result.seeded_from.length - 1} more`
}

export default function Discover() {
  const { data: results = [], isLoading, isError } = useDiscoverShows()
  const libraryIndex = useLibraryIndex()
  const createShow = useCreateShow()
  const createWatchlistEntry = useCreateWatchlistEntry()
  const ensureRssStub = useEnsureRssStub()

  const [pendingKeys, setPendingKeys] = useState<Set<string>>(new Set())
  // 'failed' — show creation itself failed, nothing was added.
  // 'partial' — the show was created, but the watchlist entry and/or RSS
  // stub afterward didn't (Promise.allSettled never rejects, so this can
  // only be detected by checking each settled result individually) — message
  // is specific about which of the two succeeded so it doesn't imply a step
  // failed when it actually went through.
  const [issueKeys, setIssueKeys] = useState<
    Map<string, { kind: 'failed' } | { kind: 'partial'; message: string }>
  >(new Map())

  async function handleAdd(result: DiscoverResult) {
    const key = `${result.id}:${result.media_type}`
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

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Discover</h1>
        <p className="text-sm text-gray-500 mt-1">
          Recommendations based on shows you&apos;re watching, filled out with what&apos;s trending.
        </p>
      </div>

      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : isError ? (
        <p className="text-red-500 text-sm">Failed to load recommendations.</p>
      ) : results.length === 0 ? (
        <p className="text-gray-500 text-sm">
          No recommendations available right now — try adding a few shows to your watchlist first.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {results.map((r) => {
            const key = `${r.id}:${r.media_type}`
            const libraryShow = libraryIndex.get(key)
            const issue = issueKeys.get(key)
            return (
              <div key={key}>
                <TmdbResultCard
                  result={r}
                  inLibraryShowId={libraryShow?.id ?? null}
                  onAdd={() => handleAdd(r)}
                  addPending={pendingKeys.has(key)}
                  addLabel="Add + Watchlist"
                  subtitle={subtitleFor(r)}
                />
                {issue?.kind === 'failed' && (
                  <p className="text-[11px] text-red-500 mt-1">Failed to add — try again.</p>
                )}
                {issue?.kind === 'partial' && (
                  <p className="text-[11px] text-amber-500 mt-1">{issue.message}</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
