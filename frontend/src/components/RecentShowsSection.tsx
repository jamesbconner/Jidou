import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { useRecentShows, useDashboardGenres, type RecentSort } from '@/hooks/useDashboard'
import { CardCarousel } from '@/components/CardCarousel'
import { RecentShowCard } from '@/components/RecentShowCard'
import { DashboardSectionControls } from '@/components/DashboardSectionControls'
import type { RecentShowItem } from '@/types/api'

interface Prefs {
  sort: RecentSort
  contentType: string
  genre: string
  limit: number
}

const DEFAULT_PREFS: Prefs = { sort: 'tracked', contentType: '', genre: '', limit: 12 }

interface Props {
  onCardClick: (show: RecentShowItem) => void
}

export function RecentShowsSection({ onCardClick }: Props) {
  const [prefs, setPrefs] = useLocalStorageState<Prefs>('jidou.dashboard.recentShows', DEFAULT_PREFS)
  const { data: shows = [], isLoading } = useRecentShows(prefs)
  const { data: genreOptions = [] } = useDashboardGenres()

  return (
    <section className="bg-white rounded-lg shadow p-4 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold">Recently Added Shows</h2>
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

      {isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {!isLoading && shows.length === 0 && (
        <p className="text-sm text-gray-400">No recently added shows match these filters.</p>
      )}
      {shows.length > 0 && (
        <CardCarousel>
          {shows.map((show) => (
            <RecentShowCard key={show.id} show={show} onClick={onCardClick} />
          ))}
        </CardCarousel>
      )}
    </section>
  )
}
