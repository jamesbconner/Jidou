import { useMemo } from 'react'
import { useSimilarShows, useLibraryIndex } from '@/hooks/useShows'
import { useAppSettings } from '@/hooks/useSettings'
import { useAddDiscoverResult, resultKey } from '@/hooks/useAddDiscoverResult'
import { CardCarousel } from '@/components/CardCarousel'
import { TmdbResultCard } from '@/components/TmdbResultCard'
import { Card } from '@/components/ui/Card'

interface Props {
  showId: number
}

/**
 * "Similar Titles" carousel on the show detail page.
 *
 * Pulls merged TMDB recommendation / similar matches for the show and renders
 * them with the same "Add + Watchlist" flow as the Discover page (via the
 * shared {@link useAddDiscoverResult} hook). In-library matches link straight
 * to their detail page; the rest offer an Add action.
 *
 * Renders nothing until it has matches to show — when the
 * `similar_titles_enabled` setting is off, while loading, when the fetch
 * errors, or when there are no matches — so the caller can drop it in
 * unconditionally without reserving layout space.
 */
export function SimilarTitlesSection({ showId }: Props) {
  const { data: appSettings } = useAppSettings()
  const enabled = appSettings?.similar_titles_enabled ?? true
  // Wait for settings to load before fetching, so a disabled feature never
  // triggers a wasted /similar request. useAppSettings is app-wide and almost
  // always warm, so this costs nothing in practice.
  const { data } = useSimilarShows(showId, !!appSettings && enabled)
  const results = useMemo(() => (Array.isArray(data) ? data : []), [data])
  const libraryIndex = useLibraryIndex()
  const { add, pendingKeys, issueKeys } = useAddDiscoverResult()

  // Memoized so CardCarousel's children identity only changes with the result
  // set or add-flow state — not on every unrelated ShowDetail re-render, which
  // would reset the user's scroll position mid-browse.
  const cards = useMemo(
    () =>
      results.map((r) => {
        const key = resultKey(r)
        const libraryShow = libraryIndex.get(key)
        const issue = issueKeys.get(key)
        return (
          <div key={key} className="w-40 shrink-0 snap-start">
            <TmdbResultCard
              result={r}
              inLibraryShowId={libraryShow?.id ?? null}
              onAdd={() => add(r)}
              addPending={pendingKeys.has(key)}
              addLabel="Add + Watchlist"
            />
            {issue?.kind === 'failed' && (
              <p className="text-xs text-red-500 dark:text-red-400 mt-1">
                Failed to add — try again.
              </p>
            )}
            {issue?.kind === 'partial' && (
              <p className="text-xs text-amber-500 dark:text-amber-400 mt-1">{issue.message}</p>
            )}
          </div>
        )
      }),
    [results, libraryIndex, issueKeys, pendingKeys, add],
  )

  if (!enabled || results.length === 0) return null

  return (
    <Card as="section" padding="md" className="space-y-3">
      <h2 className="font-semibold mb-1 dark:text-gray-100">Similar Titles</h2>
      <CardCarousel>{cards}</CardCarousel>
    </Card>
  )
}
