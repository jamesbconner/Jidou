import { useState, useMemo } from 'react'
import { useShows, useTmdbSearch, useLocalShowSearch, useCreateShow, useLibraryIndex } from '@/hooks/useShows'
import type { ShowSortOrder } from '@/hooks/useShows'
import { useWatchlist, useCreateWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
import { useOrphans, useDismissOrphan } from '@/hooks/useOrphans'
import { OrphanResolveModal } from '@/components/OrphanResolveModal'
import { DiscoverDetailModal } from '@/components/DiscoverDetailModal'
import { useDebounce } from '@/hooks/useDebounce'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { DQ_CHECKS } from '@/utils/dqChecks'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import {
  DEFAULT_MISSING_FILTERS,
  DEFAULT_SHOWS_FILTERS,
  countActiveMissingFilters,
  countActiveShowsFilters,
} from '@/utils/showFilters'
import type { MissingFilterState, ShowsFilterState } from '@/utils/showFilters'
import type { TmdbResult, OrphanedTrackingRecord } from '@/types/api'
import { LibraryTab } from './shows/LibraryTab'
import { DataQualityTab } from './shows/DataQualityTab'
import { MissingTab } from './shows/MissingTab'
import { ShowsHeader, ShowsTabBar, type ShowsTab } from './shows/ShowsHeader'
import { ShowsSearchModal, type SearchMode } from './shows/ShowsSearchModal'

/**
 * Shows page shell. It owns every query, mutation and piece of state that
 * must outlive a tab switch (filters, sort, search text, DQ filter, modals)
 * and hands typed props to the per-tab components, which only render and
 * derive from them.
 */
export default function Shows() {
  const [tab, setTab] = useState<ShowsTab>('library')
  const [dqFilter, setDqFilter] = useState<string | null>(null)
  const [missingQuery, setMissingQuery] = useState('')
  const [query, setQuery] = useState('')
  const [resolvingOrphan, setResolvingOrphan] = useState<OrphanedTrackingRecord | null>(null)
  const [tmdbModalOpen, setTmdbModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState<SearchMode>('library')
  const [detailResult, setDetailResult] = useState<TmdbResult | null>(null)

  const [pendingWatchlistShowIds, setPendingWatchlistShowIds] = useState<Set<number>>(new Set())

  // Persisted so sort/filter choices survive navigating away (e.g. into a
  // show's detail page) and back, not just page reloads.
  const [filters, setFilters] = useLocalStorageState<ShowsFilterState>(
    'jidou:shows-filters',
    DEFAULT_SHOWS_FILTERS,
  )
  const { sort } = filters
  const patchFilters = (patch: Partial<ShowsFilterState>) => setFilters({ ...filters, ...patch })
  const setSort = (v: ShowSortOrder) => patchFilters({ sort: v })

  // Independent from the library tab's filter bar — persisted separately so
  // switching tabs never cross-affects the other's filter choices.
  const [missingFilters, setMissingFilters] = useLocalStorageState<MissingFilterState>(
    'jidou:shows-missing-filters',
    DEFAULT_MISSING_FILTERS,
  )
  const missingFilterWatchlistOnly = missingFilters.filterWatchlistOnly
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

  const activeFilterCount = countActiveShowsFilters(filters)
  const activeMissingFilterCount = countActiveMissingFilters(missingFilters)

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

  function handleTrack(r: TmdbResult) {
    createShow.mutate(buildShowCreatePayload(r))
  }

  const searchModal = tmdbModalOpen && (
    <ShowsSearchModal
      mode={modalMode}
      onModeChange={setModalMode}
      query={query}
      onQueryChange={setQuery}
      debouncedQuery={debouncedQuery}
      onClose={closeModal}
      librarySearching={librarySearching}
      libraryResults={librarySearchResults}
      tmdbSearching={tmdbSearching}
      tmdbData={searchData}
      inLibraryShowId={(r) => libraryIndex.get(`${r.id}:${r.media_type ?? 'tv'}`)?.id ?? null}
      addPending={createShow.isPending}
      onAdd={handleTrack}
      onCardClick={setDetailResult}
    />
  )

  return (
    <div className="space-y-4">
      <ShowsHeader
        tab={tab}
        activeFilterCount={tab === 'missing' ? activeMissingFilterCount : activeFilterCount}
        onClearFilters={tab === 'missing' ? clearMissingFilters : clearFilters}
        sort={sort}
        onSortChange={setSort}
        onOpenSearch={() => setTmdbModalOpen(true)}
      />

      <ShowsTabBar
        tab={tab}
        onTabChange={setTab}
        libraryCount={allShows.length}
        dqIssues={totalDqIssues}
        missingEpisodes={totalMissingEpisodes}
      />

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
