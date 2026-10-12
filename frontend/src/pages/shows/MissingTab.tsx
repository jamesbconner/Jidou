import { useMemo } from 'react'
import { Link } from 'react-router'
import { Card } from '@/components/ui/Card'
import { applyMissingFilters, deriveFilterOptions } from '@/utils/showFilters'
import type { MissingFilterState } from '@/utils/showFilters'
import type { ShowList } from '@/types/api'
import { SELECT_CLS } from './styles'

interface MissingTabProps {
  allShows: ShowList[]
  /** Subset of `allShows` with at least one missing episode. */
  showsWithMissingEpisodes: ShowList[]
  isLoading: boolean
  /** Filter selection; owned by the page so it survives tab switches. */
  filters: MissingFilterState
  onFiltersChange: (patch: Partial<MissingFilterState>) => void
  /** Title search text; owned by the page so it survives tab switches. */
  query: string
  onQueryChange: (query: string) => void
  watchlistByShowId: Map<number, number>
}

/**
 * Missing-episodes table and its filter bar. Derives the visible rows from
 * page-owned props; filters, search text and the watchlist query stay in
 * `Shows` so a tab switch neither resets them nor re-fetches.
 */
export function MissingTab({
  allShows,
  showsWithMissingEpisodes,
  isLoading,
  filters,
  onFiltersChange,
  query: missingQuery,
  onQueryChange: setMissingQuery,
  watchlistByShowId,
}: MissingTabProps) {
  const {
    filterContentType: missingFilterContentType,
    filterStatus: missingFilterStatus,
    filterGenre: missingFilterGenre,
    filterLanguage: missingFilterLanguage,
    filterMinMissing,
    filterFullSeasonMissing,
    filterMaxOwned,
    filterWatchlistOnly: missingFilterWatchlistOnly,
  } = filters
  const setMissingFilterContentType = (v: string) => onFiltersChange({ filterContentType: v })
  const setMissingFilterStatus = (v: string) => onFiltersChange({ filterStatus: v })
  const setMissingFilterGenre = (v: string) => onFiltersChange({ filterGenre: v })
  const setMissingFilterLanguage = (v: string) => onFiltersChange({ filterLanguage: v })
  const setFilterMinMissing = (v: string) => onFiltersChange({ filterMinMissing: v })
  const setFilterFullSeasonMissing = (v: string) => onFiltersChange({ filterFullSeasonMissing: v })
  const setFilterMaxOwned = (v: string) => onFiltersChange({ filterMaxOwned: v })
  const setMissingFilterWatchlistOnly = (v: boolean) => onFiltersChange({ filterWatchlistOnly: v })

  const { genres: genreOptions, languages: languageOptions, statuses: statusOptions } = useMemo(
    () => deriveFilterOptions(allShows),
    [allShows],
  )
  const missingFiltered = useMemo(
    () => applyMissingFilters(
      showsWithMissingEpisodes,
      missingFilterContentType,
      missingFilterStatus,
      missingFilterGenre,
      missingFilterLanguage,
      filterMinMissing,
      filterFullSeasonMissing,
      filterMaxOwned,
      missingFilterWatchlistOnly,
      watchlistByShowId,
    ),
    [
      showsWithMissingEpisodes, missingFilterContentType, missingFilterStatus, missingFilterGenre,
      missingFilterLanguage, filterMinMissing, filterFullSeasonMissing, filterMaxOwned,
      missingFilterWatchlistOnly, watchlistByShowId,
    ],
  )
  const missingEpisodeRows = useMemo(() => {
    const q = missingQuery.trim().toLowerCase()
    return missingFiltered
      .filter((s) => !q || s.title.toLowerCase().includes(q))
      .sort((a, b) => b.missing_episode_count - a.missing_episode_count)
  }, [missingFiltered, missingQuery])
  const missingRowsTotal = useMemo(
    () => missingEpisodeRows.reduce((sum, s) => sum + s.missing_episode_count, 0),
    [missingEpisodeRows],
  )

  if (isLoading) {
    return <p className="text-gray-400 dark:text-gray-500 text-sm">Loading…</p>
  }

  return (
    <section className="space-y-3">
      {showsWithMissingEpisodes.length > 0 && (
        <div className="flex items-center gap-3 flex-wrap bg-gray-50 dark:bg-gray-900 border rounded-lg px-4 py-3">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0">Filter</span>

          <select value={missingFilterContentType} onChange={(e) => setMissingFilterContentType(e.target.value)} className={SELECT_CLS}>
            <option value="">All types</option>
            <option value="anime">Anime</option>
            <option value="tv">TV</option>
            <option value="movie">Movie</option>
            <option value="__unset__">Unset</option>
          </select>

          {statusOptions.length > 0 && (
            <select value={missingFilterStatus} onChange={(e) => setMissingFilterStatus(e.target.value)} className={SELECT_CLS}>
              <option value="">All statuses</option>
              {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          )}

          {genreOptions.length > 0 && (
            <select value={missingFilterGenre} onChange={(e) => setMissingFilterGenre(e.target.value)} className={SELECT_CLS}>
              <option value="">All genres</option>
              {genreOptions.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          )}

          {languageOptions.length > 0 && (
            <select value={missingFilterLanguage} onChange={(e) => setMissingFilterLanguage(e.target.value)} className={SELECT_CLS}>
              <option value="">All languages</option>
              {languageOptions.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
            </select>
          )}

          <select value={filterMinMissing} onChange={(e) => setFilterMinMissing(e.target.value)} className={SELECT_CLS}>
            <option value="">Any missing</option>
            <option value="eq1">Exactly 1 missing</option>
            <option value="2">2+ missing</option>
            <option value="5">5+ missing</option>
            <option value="10">10+ missing</option>
          </select>

          <select value={filterFullSeasonMissing} onChange={(e) => setFilterFullSeasonMissing(e.target.value)} className={SELECT_CLS}>
            <option value="">Any</option>
            <option value="1">Missing a whole season</option>
          </select>

          <select value={filterMaxOwned} onChange={(e) => setFilterMaxOwned(e.target.value)} className={SELECT_CLS}>
            <option value="">Any owned</option>
            <option value="1">≤1 owned</option>
            <option value="2">≤2 owned</option>
            <option value="3">≤3 owned</option>
          </select>

          <label className="flex items-center gap-1.5 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={missingFilterWatchlistOnly}
              onChange={(e) => setMissingFilterWatchlistOnly(e.target.checked)}
              className="rounded"
            />
            <span className="text-gray-700 dark:text-gray-300">Watchlist only</span>
          </label>

          <input
            type="search"
            placeholder="Filter by title…"
            value={missingQuery}
            onChange={(e) => setMissingQuery(e.target.value)}
            className="border rounded-lg px-3 py-1.5 text-sm w-56 ml-auto focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
          />
        </div>
      )}
      <p className="text-xs text-gray-500 dark:text-gray-400">
        {showsWithMissingEpisodes.length === 0
          ? `No missing episodes across ${allShows.length} show${allShows.length !== 1 ? 's' : ''}.`
          : missingEpisodeRows.length === 0
            ? `0 of ${showsWithMissingEpisodes.length} shows match the current filters.`
            : `${missingRowsTotal} missing episode${missingRowsTotal !== 1 ? 's' : ''} across ${missingEpisodeRows.length} of ${showsWithMissingEpisodes.length} show${showsWithMissingEpisodes.length !== 1 ? 's' : ''}.`}
      </p>
      {missingEpisodeRows.length > 0 && (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400 text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2 text-left">Missing Episodes</th>
                <th className="px-4 py-2 text-left">Episodes Matched</th>
                <th className="px-4 py-2 text-left">Total Episodes</th>
                <th className="px-4 py-2 text-left">Missing Seasons</th>
                <th className="px-4 py-2 text-left">Seasons Matched</th>
                <th className="px-4 py-2 text-left">Total Seasons</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {missingEpisodeRows.map((s) => (
                <tr key={s.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                  <td className="px-4 py-2">
                    <Link
                      to={`/shows/${s.id}`}
                      className="font-medium hover:underline text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)]"
                    >
                      {s.title}
                    </Link>
                    <span className="block text-xs text-gray-400 dark:text-gray-500">TMDB #{s.tmdb_id}</span>
                  </td>
                  <td className="px-4 py-2">
                    <span className="bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs font-medium rounded-full px-2 py-0.5">
                      {s.missing_episode_count}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-600 dark:text-gray-300">
                    {s.matched_episode_count}
                  </td>
                  <td className="px-4 py-2 text-gray-600 dark:text-gray-300">
                    {s.aired_episode_count}
                  </td>
                  <td className="px-4 py-2">
                    {s.missing_full_season_count > 0 ? (
                      <span className="bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300 text-xs font-medium rounded-full px-2 py-0.5">
                        {s.missing_full_season_count}
                      </span>
                    ) : (
                      <span className="text-gray-300 dark:text-gray-600">—</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-gray-600 dark:text-gray-300">
                    {s.matched_full_season_count}
                  </td>
                  <td className="px-4 py-2 text-gray-600 dark:text-gray-300">
                    {s.aired_season_count}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </section>
  )
}
