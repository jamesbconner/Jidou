import { useMemo } from 'react'
import { ShowCard } from '@/components/ShowCard'
import { applyFilters, deriveFilterOptions, sortShows } from '@/utils/showFilters'
import type { ShowsFilterState } from '@/utils/showFilters'
import type { ShowList } from '@/types/api'
import { SELECT_CLS } from './styles'

interface LibraryTabProps {
  allShows: ShowList[]
  isLoading: boolean
  /** Filter + sort selection; owned by the page so it survives tab switches. */
  filters: ShowsFilterState
  onFiltersChange: (patch: Partial<ShowsFilterState>) => void
  activeFilterCount: number
  watchlistByShowId: Map<number, number>
  pendingWatchlistShowIds: Set<number>
  onWatchlistToggle: (showId: number, watchlistEntryId: number | null) => void
}

/**
 * Library grid and its filter bar. Split out of `Shows` so the page only
 * coordinates; the filtered/sorted view is derived here from page-owned props
 * and holds no state of its own.
 */
export function LibraryTab({
  allShows,
  isLoading,
  filters,
  onFiltersChange,
  activeFilterCount,
  watchlistByShowId,
  pendingWatchlistShowIds,
  onWatchlistToggle,
}: LibraryTabProps) {
  const {
    sort, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating,
  } = filters
  const setFilterContentType = (v: string) => onFiltersChange({ filterContentType: v })
  const setFilterStatus = (v: string) => onFiltersChange({ filterStatus: v })
  const setFilterGenre = (v: string) => onFiltersChange({ filterGenre: v })
  const setFilterLanguage = (v: string) => onFiltersChange({ filterLanguage: v })
  const setFilterUpcoming = (v: boolean) => onFiltersChange({ filterUpcoming: v })
  const setFilterMinRating = (v: string) => onFiltersChange({ filterMinRating: v })

  const displayShows = useMemo(() => sortShows(allShows, sort), [allShows, sort])
  const { genres: genreOptions, languages: languageOptions, statuses: statusOptions } = useMemo(
    () => deriveFilterOptions(allShows),
    [allShows],
  )
  const filtered = useMemo(
    () => applyFilters(displayShows, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating),
    [displayShows, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating],
  )

  return (
    <>
      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap bg-gray-50 dark:bg-gray-900 border rounded-lg px-4 py-3">
        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0">Filter</span>

        <select value={filterContentType} onChange={(e) => setFilterContentType(e.target.value)} className={SELECT_CLS}>
          <option value="">All types</option>
          <option value="anime">Anime</option>
          <option value="tv">TV</option>
          <option value="movie">Movie</option>
          <option value="__unset__">Unset</option>
        </select>

        {statusOptions.length > 0 && (
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className={SELECT_CLS}>
            <option value="">All statuses</option>
            {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}

        {genreOptions.length > 0 && (
          <select value={filterGenre} onChange={(e) => setFilterGenre(e.target.value)} className={SELECT_CLS}>
            <option value="">All genres</option>
            {genreOptions.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}

        {languageOptions.length > 0 && (
          <select value={filterLanguage} onChange={(e) => setFilterLanguage(e.target.value)} className={SELECT_CLS}>
            <option value="">All languages</option>
            {languageOptions.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
          </select>
        )}

        <select value={filterMinRating} onChange={(e) => setFilterMinRating(e.target.value)} className={SELECT_CLS}>
          <option value="">Any rating</option>
          <option value="6">6+</option>
          <option value="7">7+</option>
          <option value="8">8+</option>
          <option value="9">9+</option>
        </select>

        <label className="flex items-center gap-1.5 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={filterUpcoming}
            onChange={(e) => setFilterUpcoming(e.target.checked)}
            className="rounded"
          />
          <span className="text-gray-700 dark:text-gray-300">Upcoming episode</span>
        </label>
      </div>

      <section>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          {activeFilterCount > 0 ? `${filtered.length} of ${allShows.length} shows` : `${allShows.length} show${allShows.length !== 1 ? 's' : ''}`}
        </p>
        {isLoading ? (
          <p className="text-gray-400 dark:text-gray-500 text-sm">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="text-gray-500 dark:text-gray-400 text-sm">
            {allShows.length === 0 ? 'No shows in library yet. Search above to add one.' : 'No shows match the current filters.'}
          </p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {filtered.map((s) => (
              <ShowCard
                key={s.id}
                show={s}
                watchlistEntryId={watchlistByShowId.get(s.id) ?? null}
                onWatchlistToggle={onWatchlistToggle}
                watchlistPending={pendingWatchlistShowIds.has(s.id)}
              />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
