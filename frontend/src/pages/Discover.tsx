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
  const [failedKeys, setFailedKeys] = useState<Set<string>>(new Set())

  async function handleAdd(result: DiscoverResult) {
    const key = `${result.id}:${result.media_type}`
    setPendingKeys((prev) => new Set(prev).add(key))
    setFailedKeys((prev) => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
    try {
      const show = await createShow.mutateAsync(buildShowCreatePayload(result))
      await Promise.allSettled([
        createWatchlistEntry.mutateAsync({ show_id: show.id }),
        ensureRssStub.mutateAsync(show.id),
      ])
    } catch {
      setFailedKeys((prev) => new Set(prev).add(key))
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
                {failedKeys.has(key) && (
                  <p className="text-[11px] text-red-500 mt-1">Failed to add — try again.</p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
