import { useState } from 'react'
import { useDiscoverShows, useLibraryIndex } from '@/hooks/useShows'
import { useAddDiscoverResult, resultKey } from '@/hooks/useAddDiscoverResult'
import { TmdbResultCard } from '@/components/TmdbResultCard'
import { DiscoverDetailModal } from '@/components/DiscoverDetailModal'
import type { DiscoverResult } from '@/types/api'

function subtitleFor(result: DiscoverResult): string {
  if (result.seeded_from.length === 0) return 'Trending'
  if (result.seeded_from.length === 1) return `Because you watch ${result.seeded_from[0]}`
  return `Because you watch ${result.seeded_from[0]} +${result.seeded_from.length - 1} more`
}

export default function Discover() {
  const { data: results = [], isLoading, isError } = useDiscoverShows()
  const libraryIndex = useLibraryIndex()
  const { add: handleAdd, pendingKeys, issueKeys } = useAddDiscoverResult()

  const [detailResult, setDetailResult] = useState<DiscoverResult | null>(null)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold dark:text-gray-100">Discover</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Recommendations based on shows you&apos;re watching, filled out with what&apos;s trending.
        </p>
      </div>

      {isLoading ? (
        <p className="text-gray-400 dark:text-gray-500 text-sm">Loading…</p>
      ) : isError ? (
        <p className="text-red-500 dark:text-red-400 text-sm">Failed to load recommendations.</p>
      ) : results.length === 0 ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">
          No recommendations available right now — try adding a few shows to your watchlist first.
        </p>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          {results.map((r) => {
            const key = resultKey(r)
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
                  onCardClick={() => setDetailResult(r)}
                />
                {issue?.kind === 'failed' && (
                  <p className="text-[11px] text-red-500 dark:text-red-400 mt-1">Failed to add — try again.</p>
                )}
                {issue?.kind === 'partial' && (
                  <p className="text-[11px] text-amber-500 dark:text-amber-400 mt-1">{issue.message}</p>
                )}
              </div>
            )
          })}
        </div>
      )}

      {detailResult && (
        <DiscoverDetailModal
          result={detailResult}
          inLibraryShowId={
            libraryIndex.get(`${detailResult.id}:${detailResult.media_type}`)?.id ?? null
          }
          onClose={() => setDetailResult(null)}
          onAdd={() => handleAdd(detailResult)}
          addPending={pendingKeys.has(resultKey(detailResult))}
          addLabel="Add + Watchlist"
        />
      )}
    </div>
  )
}
