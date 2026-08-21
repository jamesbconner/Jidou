import { useMemo } from 'react'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { useRecentEpisodes, useDashboardGenres, type RecentSort } from '@/hooks/useDashboard'
import { useAppSettings } from '@/hooks/useSettings'
import { CardCarousel } from '@/components/CardCarousel'
import { RecentEpisodeCard } from '@/components/RecentEpisodeCard'
import { DashboardSectionControls } from '@/components/DashboardSectionControls'
import { Card } from '@/components/ui/Card'
import type { RecentEpisodeItem } from '@/types/api'

interface Prefs {
  sort: RecentSort
  contentType: string
  genre: string
  limit: number
}

const DEFAULT_PREFS: Prefs = { sort: 'tracked', contentType: '', genre: '', limit: 12 }

interface Props {
  onCardClick: (episode: RecentEpisodeItem, sort: RecentSort) => void
}

export function RecentEpisodesSection({ onCardClick }: Props) {
  const [prefs, setPrefs] = useLocalStorageState<Prefs>(
    'jidou.dashboard.recentEpisodes',
    DEFAULT_PREFS,
  )
  const { data: episodes = [], isLoading, isError } = useRecentEpisodes(prefs)
  const { data: genreOptions = [] } = useDashboardGenres()
  const { data: appSettings } = useAppSettings()
  const preferPosters = appSettings?.recent_episodes_prefer_posters ?? false

  // Memoized so CardCarousel's children reference only changes when the
  // actual result set or sort changes — not on every unrelated parent
  // re-render, which would otherwise reset the user's scroll position.
  const cards = useMemo(
    () =>
      episodes.map((episode) => (
        <RecentEpisodeCard
          key={episode.id}
          episode={episode}
          sort={prefs.sort}
          preferPosters={preferPosters}
          onClick={(clicked) => onCardClick(clicked, prefs.sort)}
        />
      )),
    [episodes, prefs.sort, preferPosters, onCardClick],
  )

  return (
    <Card as="section" padding="md" className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Recently Added Episodes</h2>
        <DashboardSectionControls
          sort={prefs.sort}
          onSortChange={(sort) => setPrefs({ ...prefs, sort })}
          contentType={prefs.contentType}
          onContentTypeChange={(contentType) => setPrefs({ ...prefs, contentType })}
          genre={prefs.genre}
          onGenreChange={(genre) => setPrefs({ ...prefs, genre })}
          genreOptions={genreOptions}
          limit={prefs.limit}
          onLimitChange={(limit) => setPrefs({ ...prefs, limit })}
        />
      </div>

      {isLoading && <p className="text-sm text-gray-400 dark:text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-500 dark:text-red-400">Failed to load recently added episodes.</p>}
      {!isLoading && !isError && episodes.length === 0 && (
        <p className="text-sm text-gray-400 dark:text-gray-500">No recently added episodes match these filters.</p>
      )}
      {episodes.length > 0 && <CardCarousel>{cards}</CardCarousel>}
    </Card>
  )
}
