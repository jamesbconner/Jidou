import { useMemo } from 'react'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { useRecentShows, useDashboardGenres, type RecentSort } from '@/hooks/useDashboard'
import { CardCarousel } from '@/components/CardCarousel'
import { RecentShowCard } from '@/components/RecentShowCard'
import { DashboardSectionControls } from '@/components/DashboardSectionControls'
import { Card } from '@/components/ui/Card'
import type { RecentShowItem } from '@/types/api'

interface Prefs {
  sort: RecentSort
  contentType: string
  genre: string
  limit: number
}

const DEFAULT_PREFS: Prefs = { sort: 'tracked', contentType: '', genre: '', limit: 12 }

interface Props {
  onCardClick: (show: RecentShowItem, sort: RecentSort) => void
}

export function RecentShowsSection({ onCardClick }: Props) {
  const [prefs, setPrefs] = useLocalStorageState<Prefs>('jidou.dashboard.recentShows', DEFAULT_PREFS)
  const { data: shows = [], isLoading, isError } = useRecentShows(prefs)
  const { data: genreOptions = [] } = useDashboardGenres()

  // Memoized so CardCarousel's children reference only changes when the
  // actual result set or sort changes — not on every unrelated parent
  // re-render (dashboard polling, sibling state updates), which would
  // otherwise reset the user's scroll position while they're browsing.
  const cards = useMemo(
    () =>
      shows.map((show) => (
        <RecentShowCard
          key={show.id}
          show={show}
          sort={prefs.sort}
          onClick={(clicked) => onCardClick(clicked, prefs.sort)}
        />
      )),
    [shows, prefs.sort, onCardClick],
  )

  return (
    <Card as="section" padding="md" className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Recently Added Shows</h2>
        <DashboardSectionControls
          sort={prefs.sort}
          onSortChange={(sort) => setPrefs({ ...prefs, sort })}
          contentType={prefs.contentType}
          onContentTypeChange={(contentType) => setPrefs({ ...prefs, contentType })}
          contentTypeOptions={['anime', 'tv']}
          genre={prefs.genre}
          onGenreChange={(genre) => setPrefs({ ...prefs, genre })}
          genreOptions={genreOptions}
          limit={prefs.limit}
          onLimitChange={(limit) => setPrefs({ ...prefs, limit })}
        />
      </div>

      {isLoading && <p className="text-sm text-gray-400 dark:text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-500 dark:text-red-400">Failed to load recently added shows.</p>}
      {!isLoading && !isError && shows.length === 0 && (
        <p className="text-sm text-gray-400 dark:text-gray-500">No recently added shows match these filters.</p>
      )}
      {shows.length > 0 && <CardCarousel>{cards}</CardCarousel>}
    </Card>
  )
}
