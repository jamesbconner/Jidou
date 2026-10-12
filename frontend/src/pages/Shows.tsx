import { useState, useMemo } from 'react'
import { Link } from 'react-router'
import { TmdbResultCard } from '@/components/TmdbResultCard'
import { useShows, useTmdbSearch, useLocalShowSearch, useCreateShow, useLibraryIndex, SHOW_SORT_LABELS } from '@/hooks/useShows'
import type { ShowSortOrder } from '@/hooks/useShows'
import { useWatchlist, useCreateWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
import { useOrphans, useDismissOrphan } from '@/hooks/useOrphans'
import { OrphanResolveModal } from '@/components/OrphanResolveModal'
import { DiscoverDetailModal } from '@/components/DiscoverDetailModal'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import { useDebounce } from '@/hooks/useDebounce'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { DQ_CHECKS } from '@/utils/dqChecks'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import { DEFAULT_MISSING_FILTERS, DEFAULT_SHOWS_FILTERS } from '@/utils/showFilters'
import type { MissingFilterState, ShowsFilterState } from '@/utils/showFilters'
import type { TmdbResult, OrphanedTrackingRecord } from '@/types/api'
import { LibraryTab } from './shows/LibraryTab'
import { DataQualityTab } from './shows/DataQualityTab'
import { MissingTab } from './shows/MissingTab'
import { SELECT_CLS } from './shows/styles'

const TMDB_IMG = '/api/images/w185'

type Tab = 'library' | 'data' | 'missing'

/**
 * Shows page shell. It owns every query, mutation and piece of state that
 * must outlive a tab switch (filters, sort, search text, DQ filter, modals)
 * and hands typed props to the per-tab components, which only render and
 * derive from them.
 */
export default function Shows() {
  const [tab, setTab] = useState<Tab>('library')
  const [dqFilter, setDqFilter] = useState<string | null>(null)
  const [missingQuery, setMissingQuery] = useState('')
  const [query, setQuery] = useState('')
  const [resolvingOrphan, setResolvingOrphan] = useState<OrphanedTrackingRecord | null>(null)
  const [tmdbModalOpen, setTmdbModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState<'library' | 'tmdb'>('library')
  const [detailResult, setDetailResult] = useState<TmdbResult | null>(null)

  const [pendingWatchlistShowIds, setPendingWatchlistShowIds] = useState<Set<number>>(new Set())

  // Persisted so sort/filter choices survive navigating away (e.g. into a
  // show's detail page) and back, not just page reloads.
  const [filters, setFilters] = useLocalStorageState<ShowsFilterState>(
    'jidou:shows-filters',
    DEFAULT_SHOWS_FILTERS,
  )
  const {
    sort, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating,
  } = filters
  const patchFilters = (patch: Partial<ShowsFilterState>) => setFilters({ ...filters, ...patch })
  const setSort = (v: ShowSortOrder) => patchFilters({ sort: v })

  // Independent from the library tab's filter bar — persisted separately so
  // switching tabs never cross-affects the other's filter choices.
  const [missingFilters, setMissingFilters] = useLocalStorageState<MissingFilterState>(
    'jidou:shows-missing-filters',
    DEFAULT_MISSING_FILTERS,
  )
  const {
    filterContentType: missingFilterContentType,
    filterStatus: missingFilterStatus,
    filterGenre: missingFilterGenre,
    filterLanguage: missingFilterLanguage,
    filterMinMissing,
    filterFullSeasonMissing,
    filterMaxOwned,
    filterWatchlistOnly: missingFilterWatchlistOnly,
  } = missingFilters
  const patchMissingFilters = (patch: Partial<MissingFilterState>) =>
    setMissingFilters({ ...missingFilters, ...patch })

  const debouncedQuery = useDebounce(query, 300)

  // Single fetch covers both the modal search pool and the display grid.
  const { data: allShows = [], isLoading } = useShows('title_asc', 10000)
  const { data: searchData, isLoading: tmdbSearching } = useTmdbSearch(
    modalMode === 'tmdb' && query.length >= 2 ? debouncedQuery : '',
    'multi',
  )
  const { data: orphans = [] } = useOrphans()
  const dismissOrphan = useDismissOrphan()
  const createShow = useCreateShow()

  // High limit mirrors allShows — covers the full library without pagination gaps.
  // TODO: this is a genuine bulk lookup (watchlist state per visible show), so a
  // by-show filter can't replace it — but the hardcoded limit=10000 sentinel is a smell.
  // Consider a lighter summary endpoint/field (show_id + status only, no embedded show)
  // once the watchlist is large enough for this to matter.
  const { data: watchlistEntries = [], isLoading: watchlistLoading } = useWatchlist(undefined, 10000)
  const createWatchlistEntry = useCreateWatchlistEntry()
  const deleteWatchlistEntry = useDeleteWatchlistEntry()

  // Map show_id → watchlist entry id for O(1) lookup on each card.
  const watchlistByShowId = useMemo(
    () => new Map(watchlistEntries.map((e) => [e.show_id, e.id])),
    [watchlistEntries],
  )

  function handleWatchlistToggle(showId: number, watchlistEntryId: number | null) {
    if (pendingWatchlistShowIds.has(showId)) return
    setPendingWatchlistShowIds((prev) => new Set(prev).add(showId))
    const settle = () =>
      setPendingWatchlistShowIds((prev) => {
        const next = new Set(prev)
        next.delete(showId)
        return next
      })
    if (watchlistEntryId != null) {
      deleteWatchlistEntry.mutate(watchlistEntryId, { onSettled: settle })
    } else {
      createWatchlistEntry.mutate({ show_id: showId }, { onSettled: settle })
    }
  }

  const libraryIndex = useLibraryIndex()

  // Server-side match on title, alias, sys_name and folder name.
  const { data: librarySearchResults = [], isFetching: librarySearching } = useLocalShowSearch(
    modalMode === 'library' ? debouncedQuery : '',
    10,
  )

  // The watchlist-only filter reads watchlistByShowId, which is empty until
  // the watchlist query resolves — without this, rows can flash to "no
  // matches" while the (slower) watchlist fetch is still in flight.
  const missingTabLoading = isLoading || (missingFilterWatchlistOnly && watchlistLoading)

  // Tab-bar badges need these totals even while their tab is not mounted.
  const totalDqIssues = useMemo(
    () => allShows.filter((s) => DQ_CHECKS.some((c) => c.test(s))).length,
    [allShows],
  )
  const showsWithMissingEpisodes = useMemo(
    () => allShows.filter((s) => s.missing_episode_count > 0),
    [allShows],
  )
  const totalMissingEpisodes = useMemo(
    () => showsWithMissingEpisodes.reduce((sum, s) => sum + s.missing_episode_count, 0),
    [showsWithMissingEpisodes],
  )

  const activeFilterCount = [
    filterContentType, filterStatus, filterGenre, filterLanguage, filterMinRating,
  ].filter(Boolean).length + (filterUpcoming ? 1 : 0)

  const activeMissingFilterCount = [
    missingFilterContentType, missingFilterStatus, missingFilterGenre, missingFilterLanguage,
    filterMinMissing, filterFullSeasonMissing, filterMaxOwned,
  ].filter(Boolean).length + (missingFilterWatchlistOnly ? 1 : 0)

  function clearFilters() {
    setFilters({
      ...filters,
      filterContentType: '',
      filterStatus: '',
      filterGenre: '',
      filterLanguage: '',
      filterUpcoming: false,
      filterMinRating: '',
    })
  }

  function clearMissingFilters() {
    setMissingFilters(DEFAULT_MISSING_FILTERS)
  }

  function closeModal() {
    setTmdbModalOpen(false)
    setQuery('')
    setDetailResult(null)
  }

  function switchModalMode(mode: 'library' | 'tmdb') {
    setModalMode(mode)
  }

  function handleTrack(r: TmdbResult) {
    createShow.mutate(buildShowCreatePayload(r))
  }

  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
    }`

  const searchModal = tmdbModalOpen && (
      <Modal onClose={closeModal} tone="light" maxWidth="2xl" closeOnBackdropClick className="max-h-[80vh] flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b">
            <h3 className="font-semibold dark:text-gray-100">Search Shows</h3>
            <ModalCloseButton onClose={closeModal} />
          </div>

          {/* Library / TMDB pill toggle */}
          <div className="px-5 pt-4">
            <div className="flex rounded-lg border text-sm overflow-hidden">
              {(['library', 'tmdb'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => switchModalMode(m)}
                  className={`flex-1 py-2 font-medium transition-colors ${
                    modalMode === m ? 'bg-[var(--color-ocean-600)] text-white' : 'bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'
                  }`}
                >
                  {m === 'library' ? 'Library' : 'TMDB'}
                </button>
              ))}
            </div>
          </div>

          <div className="px-5 pt-3 pb-3 border-b">
            <input
              type="search"
              autoFocus
              placeholder={modalMode === 'library' ? 'Search your library…' : 'Search TMDB…'}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
            />
          </div>

          <div className="overflow-y-auto flex-1 p-5">
            {modalMode === 'library' ? (
              query.trim().length < 2 ? (
                <p className="text-sm text-gray-400 dark:text-gray-500">Type at least 2 characters to search your library.</p>
              ) : librarySearching || debouncedQuery !== query ? (
                <p className="text-sm text-gray-400 dark:text-gray-500">Searching…</p>
              ) : librarySearchResults.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">No shows found for &quot;{query}&quot;.</p>
              ) : (
                <div className="space-y-1.5">
                  {librarySearchResults.map((s) => (
                    <Link
                      key={s.id}
                      to={`/shows/${s.id}`}
                      onClick={closeModal}
                      className="flex items-center gap-3 px-3 py-2 rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                    >
                      {s.poster_path ? (
                        <img src={`${TMDB_IMG}${s.poster_path}`} alt={s.title} className="w-8 h-12 object-cover rounded flex-shrink-0" loading="lazy" />
                      ) : (
                        <div className="w-8 h-12 bg-gray-100 dark:bg-gray-800 rounded flex-shrink-0" />
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate dark:text-gray-100">{s.title}</p>
                        <p className="text-xs text-gray-400 dark:text-gray-500">
                          {s.release_date?.slice(0, 4)}{s.content_type ? ` · ${s.content_type}` : ''}
                          {s.matched_on !== 'title' ? ` · matched ${s.matched_on === 'path' ? 'folder' : s.matched_on === 'sys_name' ? 'system name' : 'alias'}` : ''}
                        </p>
                      </div>
                      <span className="text-xs text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] shrink-0">View →</span>
                    </Link>
                  ))}
                </div>
              )
            ) : (
              query.trim().length < 2 ? (
                <p className="text-sm text-gray-400 dark:text-gray-500">Type at least 2 characters to search TMDB.</p>
              ) : tmdbSearching || debouncedQuery !== query ? (
                <p className="text-sm text-gray-400 dark:text-gray-500">Searching…</p>
              ) : !searchData || searchData.results.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400">No results for &quot;{debouncedQuery}&quot;.</p>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {searchData.results.slice(0, 12).map((r) => {
                    const mediaType = r.media_type ?? 'tv'
                    const libraryShow = libraryIndex.get(`${r.id}:${mediaType}`)
                    return (
                      <TmdbResultCard
                        key={`${r.id}:${mediaType}`}
                        result={r}
                        inLibraryShowId={libraryShow?.id ?? null}
                        onAdd={() => handleTrack(r)}
                        addPending={createShow.isPending}
                        onNavigate={closeModal}
                        onCardClick={() => setDetailResult(r)}
                      />
                    )
                  })}
                </div>
              )
            )}
          </div>
      </Modal>
  )

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold mr-auto dark:text-gray-100">Shows</h1>
        {tab === 'library' && activeFilterCount > 0 && (
          <Button onClick={clearFilters} variant="secondary" tone="light" size="sm">
            Clear filters ({activeFilterCount})
          </Button>
        )}
        {tab === 'missing' && activeMissingFilterCount > 0 && (
          <Button onClick={clearMissingFilters} variant="secondary" tone="light" size="sm">
            Clear filters ({activeMissingFilterCount})
          </Button>
        )}
        {tab === 'library' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as ShowSortOrder)} className={SELECT_CLS}>
            {(Object.entries(SHOW_SORT_LABELS) as [ShowSortOrder, string][]).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        )}
        <button
          onClick={() => setTmdbModalOpen(true)}
          className="border rounded-lg px-3 py-2 text-sm w-64 text-left text-gray-400 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-500 dark:hover:bg-gray-800"
        >
          Search shows…
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b">
        <button className={tabCls('library')} onClick={() => setTab('library')}>
          Shows in Library ({allShows.length})
        </button>
        <button className={tabCls('data')} onClick={() => setTab('data')}>
          Data Quality
          {totalDqIssues > 0 && (
            <span className="ml-2 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded-full px-1.5 py-0.5">
              {totalDqIssues}
            </span>
          )}
        </button>
        <button className={tabCls('missing')} onClick={() => setTab('missing')}>
          Missing Episodes
          {totalMissingEpisodes > 0 && (
            <span className="ml-2 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded-full px-1.5 py-0.5">
              {totalMissingEpisodes}
            </span>
          )}
        </button>
      </div>

      {tab === 'library' && (
        <LibraryTab
          allShows={allShows}
          isLoading={isLoading}
          filters={filters}
          onFiltersChange={patchFilters}
          activeFilterCount={activeFilterCount}
          watchlistByShowId={watchlistByShowId}
          pendingWatchlistShowIds={pendingWatchlistShowIds}
          onWatchlistToggle={handleWatchlistToggle}
          searchModal={searchModal}
        />
      )}

      {/* On the library tab the modal is rendered by LibraryTab, in its original DOM slot. */}
      {tab !== 'library' && searchModal}

      {tab === 'data' && (
        <DataQualityTab
          allShows={allShows}
          isLoading={isLoading}
          orphans={orphans}
          dqFilter={dqFilter}
          onDqFilterChange={setDqFilter}
          onResolveOrphan={setResolvingOrphan}
          onDismissOrphan={(id) => dismissOrphan.mutate(id)}
          dismissingOrphanId={dismissOrphan.isPending ? (dismissOrphan.variables ?? null) : null}
        />
      )}

      {tab === 'missing' && (
        <MissingTab
          allShows={allShows}
          showsWithMissingEpisodes={showsWithMissingEpisodes}
          isLoading={missingTabLoading}
          filters={missingFilters}
          onFiltersChange={patchMissingFilters}
          query={missingQuery}
          onQueryChange={setMissingQuery}
          watchlistByShowId={watchlistByShowId}
        />
      )}

      {resolvingOrphan && (
        <OrphanResolveModal
          orphan={resolvingOrphan}
          onClose={() => setResolvingOrphan(null)}
        />
      )}

      {detailResult && (
        <DiscoverDetailModal
          result={detailResult}
          inLibraryShowId={
            libraryIndex.get(`${detailResult.id}:${detailResult.media_type ?? 'tv'}`)?.id ?? null
          }
          onClose={() => setDetailResult(null)}
          onNavigate={closeModal}
          onAdd={() => handleTrack(detailResult)}
          addPending={createShow.isPending}
        />
      )}
    </div>
  )
}
