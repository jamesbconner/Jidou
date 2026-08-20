import { useState, useRef, useEffect, useMemo } from 'react'
import { Link } from 'react-router'
import {
  DndContext,
  closestCenter,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useWatchlist, useCreateWatchlistEntry, useDeleteWatchlistEntry, useReorderWatchlist } from '@/hooks/useWatchlist'
import { useShows, useSearchShows, useCreateShow, useLibraryIndex } from '@/hooks/useShows'
import { useDebounce } from '@/hooks/useDebounce'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import { WatchlistStatusSelect } from '@/components/WatchlistStatusSelect'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { STATUS_COLOR, STATUS_LABEL, STATUS_OPTIONS } from '@/utils/watchlistStatus'
import type { WatchlistStatus, WatchlistRead, ShowList, TmdbResult } from '@/types/api'

const TMDB_IMG = '/api/images/w92'
const TMDB_BACKDROP_IMG = '/api/images/w500'
// Stable reference so the `entries` destructuring default doesn't create a
// new array identity on every render while the query is loading — a fresh
// [] each render would make the position-merge effect below (which depends
// on `entries`) re-run and call setState every render, looping forever.
const EMPTY_WATCHLIST_ENTRIES: WatchlistRead[] = []

// ─── Drag handle icon ─────────────────────────────────────────────────────────

function GripIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
      <circle cx="4" cy="3" r="1.5" />
      <circle cx="10" cy="3" r="1.5" />
      <circle cx="4" cy="7" r="1.5" />
      <circle cx="10" cy="7" r="1.5" />
      <circle cx="4" cy="11" r="1.5" />
      <circle cx="10" cy="11" r="1.5" />
    </svg>
  )
}

// ─── Sortable table row ───────────────────────────────────────────────────────

interface SortableRowProps {
  entry: WatchlistRead
  index: number
  onDelete: (id: number) => void
  isDeletePending: boolean
  dragEnabled: boolean
}

function SortableRow({ entry, index, onDelete, isDeletePending, dragEnabled }: SortableRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: entry.id })

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    position: isDragging ? 'relative' : undefined,
    zIndex: isDragging ? 1 : undefined,
    userSelect: 'none',
  }

  return (
    <tr ref={setNodeRef} style={style} {...attributes} className="hover:bg-gray-50">
      <td
        {...(dragEnabled ? listeners : {})}
        className={`px-2 py-2 ${dragEnabled ? 'text-gray-400 hover:text-gray-600 cursor-grab active:cursor-grabbing' : 'text-gray-300 cursor-not-allowed'}`}
        title={dragEnabled ? 'Drag to reorder' : 'Clear status filter to reorder'}
      >
        <GripIcon />
      </td>
      <td className="px-4 py-2 text-gray-400 text-xs">{index + 1}</td>
      <td className="px-2 py-2 w-48">
        {entry.show.backdrop_path ? (
          <img
            src={`${TMDB_BACKDROP_IMG}${entry.show.backdrop_path}`}
            alt=""
            className="w-48 aspect-video object-cover rounded-lg"
            loading="lazy"
          />
        ) : (
          <div className="w-48 aspect-video bg-gray-100 rounded-lg flex items-center justify-center text-gray-400 text-[10px]">
            No image
          </div>
        )}
      </td>
      <td className="px-4 py-2">
        <Link
          to={`/shows/${entry.show_id}`}
          className="font-medium hover:underline text-blue-700"
        >
          {entry.show.title}
        </Link>
        <span className="block text-xs text-gray-400">TMDB #{entry.show.tmdb_id}</span>
      </td>
      <td className="px-4 py-2">
        <WatchlistStatusSelect id={entry.id} current={entry.status as WatchlistStatus} />
      </td>
      <td className="px-4 py-2">
        {entry.next_up ? (
          <>
            <span className="block font-medium">
              S{String(entry.next_up.season_number).padStart(2, '0')}E
              {String(entry.next_up.episode_number).padStart(2, '0')}
              {entry.next_up.file_tracked && ' ✓'}
            </span>
            {entry.next_up.air_date && (
              <span className="block text-xs text-gray-400">{entry.next_up.air_date}</span>
            )}
          </>
        ) : (
          <span className="text-gray-300">—</span>
        )}
      </td>
      <td className="px-4 py-2 text-right">
        <button
          onClick={() => onDelete(entry.id)}
          disabled={isDeletePending}
          className="text-xs text-red-500 hover:underline disabled:opacity-50"
        >
          Remove
        </button>
      </td>
    </tr>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Watchlist() {
  const [statusFilter, setStatusFilter] = useState<WatchlistStatus | ''>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchMode, setSearchMode] = useState<'library' | 'tmdb'>('library')
  const [searchModalOpen, setSearchModalOpen] = useState(false)
  // Per-item pending sets so concurrent adds don't clobber each other's loading state.
  const [pendingLibraryIds, setPendingLibraryIds] = useState<Set<number>>(new Set())
  const [pendingTmdbIds, setPendingTmdbIds] = useState<Set<number>>(new Set())
  const [orderedEntries, setOrderedEntries] = useState<WatchlistRead[]>([])
  const [reorderError, setReorderError] = useState<string | null>(null)

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 5 } }),
  )

  const debouncedQuery = useDebounce(searchQuery, 300)

  useEffect(() => {
    if (!searchModalOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { setSearchModalOpen(false); setSearchQuery('') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [searchModalOpen])

  const { data: entries = EMPTY_WATCHLIST_ENTRIES, isLoading } = useWatchlist(statusFilter || undefined)
  // Unfiltered full list for search cross-reference — independent of the status filter and
  // the default limit=50 that powers the table, so search badges are always accurate.
  // TODO: this is a genuine bulk lookup (status per show across search results), so a
  // by-show filter can't replace it — but the hardcoded limit=10000 sentinel is a smell.
  // Consider a lighter summary endpoint/field (show_id + status only, no embedded show)
  // once the watchlist is large enough for this to matter.
  const { data: allEntries = [] } = useWatchlist(undefined, 10000)
  const { data: allShows = [] } = useShows('title_asc', 10000)
  const { data: tmdbData, isLoading: tmdbLoading } = useSearchShows(
    searchMode === 'tmdb' && searchQuery.length >= 2 ? debouncedQuery : '',
    'multi',
  )

  const createWatchlistEntry = useCreateWatchlistEntry()
  const createShow = useCreateShow()
  const deleteEntry = useDeleteWatchlistEntry()
  const reorderWatchlist = useReorderWatchlist()

  // Reordering within a filtered view would assign 1-based positions to a subset,
  // colliding with hidden entries' positions after the filter is cleared.
  const dragEnabled = statusFilter === ''

  const prevFilterRef = useRef(statusFilter)
  useEffect(() => {
    const filterChanged = prevFilterRef.current !== statusFilter
    prevFilterRef.current = statusFilter
    if (filterChanged) {
      // Filter changed — restore server position order so newly visible entries
      // appear in their saved positions, not appended at the end of the old slice.
      setOrderedEntries(entries as WatchlistRead[])
      return
    }
    // Merge: preserve drag order for existing entries, drop removed ones,
    // append new additions at the end.
    setOrderedEntries((prev) => {
      const serverMap = new Map((entries as WatchlistRead[]).map((e) => [e.id, e]))
      const kept = prev.filter((e) => serverMap.has(e.id)).map((e) => serverMap.get(e.id)!)
      const keptIds = new Set(kept.map((e) => e.id))
      const added = (entries as WatchlistRead[]).filter((e) => !keptIds.has(e.id))
      return [...kept, ...added]
    })
  }, [entries, statusFilter])

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    if (reorderWatchlist.isPending) return
    const oldIndex = orderedEntries.findIndex((e) => e.id === active.id)
    const newIndex = orderedEntries.findIndex((e) => e.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const snapshot = orderedEntries.slice()
    const reordered = arrayMove(orderedEntries, oldIndex, newIndex)
    setReorderError(null)
    setOrderedEntries(reordered)
    reorderWatchlist.mutate(reordered, {
      onError: (err) => {
        setOrderedEntries(snapshot)
        setReorderError(err instanceof Error ? err.message : 'Failed to save order')
      },
    })
  }

  // Map show_id → watchlist status for result-row lookup (uses full unfiltered list)
  const watchlistStatusByShowId = useMemo(
    () => new Map(allEntries.map((e) => [e.show_id, e.status as WatchlistStatus])),
    [allEntries],
  )

  const libraryByTmdbId = useLibraryIndex()

  const libraryResults: ShowList[] = useMemo(() => {
    if (!searchQuery.trim() || searchMode !== 'library') return []
    const q = searchQuery.toLowerCase()
    return allShows.filter((s) => s.title.toLowerCase().includes(q)).slice(0, 8)
  }, [allShows, searchQuery, searchMode])

  const tmdbResults: TmdbResult[] = useMemo(
    () => (searchMode === 'tmdb' ? (tmdbData?.results ?? []).slice(0, 8) : []),
    [tmdbData, searchMode],
  )

  function addShowId(set: Set<number>, id: number) {
    return new Set(set).add(id)
  }
  function removeShowId(set: Set<number>, id: number) {
    const next = new Set(set); next.delete(id); return next
  }

  function handleAddFromLibrary(showId: number) {
    if (pendingLibraryIds.has(showId)) return
    setPendingLibraryIds((s) => addShowId(s, showId))
    createWatchlistEntry.mutate(
      { show_id: showId },
      { onSettled: () => setPendingLibraryIds((s) => removeShowId(s, showId)) },
    )
  }

  function handleAddFromTmdb(result: TmdbResult) {
    if (pendingTmdbIds.has(result.id)) return
    const existing = libraryByTmdbId.get(`${result.id}:${result.media_type ?? 'tv'}`)
    if (existing) {
      if (pendingLibraryIds.has(existing.id)) return
      setPendingLibraryIds((s) => addShowId(s, existing.id))
      createWatchlistEntry.mutate(
        { show_id: existing.id },
        { onSettled: () => setPendingLibraryIds((s) => removeShowId(s, existing.id)) },
      )
      return
    }
    setPendingTmdbIds((s) => addShowId(s, result.id))
    createShow.mutate(buildShowCreatePayload(result), {
      onSuccess: (show) => createWatchlistEntry.mutate(
        { show_id: show.id },
        { onSettled: () => setPendingTmdbIds((s) => removeShowId(s, result.id)) },
      ),
      onError: () => setPendingTmdbIds((s) => removeShowId(s, result.id)),
    })
  }

  const hasResults = searchMode === 'library' ? libraryResults.length > 0 : tmdbResults.length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold mr-auto">Watchlist</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as WatchlistStatus | '')}
          className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>
        <button
          onClick={() => setSearchModalOpen(true)}
          className="border rounded-lg px-3 py-2 text-sm text-left text-gray-400 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 w-56"
        >
          Search shows to add…
        </button>
      </div>

      <p className="text-sm text-gray-500">
        Keep track of shows you want to watch, are currently watching, or have finished.
      </p>

      {/* Search modal */}
      {searchModalOpen && (
        <Modal
          onClose={() => { setSearchModalOpen(false); setSearchQuery('') }}
          tone="light"
          maxWidth="2xl"
          closeOnBackdropClick
          className="max-h-[80vh] flex flex-col"
        >
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h3 className="font-semibold">Add to Watchlist</h3>
              <button
                onClick={() => { setSearchModalOpen(false); setSearchQuery('') }}
                className="text-gray-400 hover:text-gray-700 text-lg leading-none"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {/* Library / TMDB toggle */}
            <div className="px-5 pt-4">
              <div className="flex items-center justify-center gap-3 text-sm">
                <span className={searchMode === 'library' ? 'font-medium text-gray-900' : 'text-gray-400'}>
                  Library
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={searchMode === 'tmdb'}
                  aria-label="Toggle between library and TMDB search"
                  onClick={() => setSearchMode((m) => (m === 'library' ? 'tmdb' : 'library'))}
                  className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
                    searchMode === 'tmdb' ? 'bg-blue-600' : 'bg-gray-300'
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                      searchMode === 'tmdb' ? 'translate-x-4' : 'translate-x-0.5'
                    }`}
                  />
                </button>
                <span className={searchMode === 'tmdb' ? 'font-medium text-gray-900' : 'text-gray-400'}>
                  TMDB
                </span>
              </div>
            </div>

            <div className="px-5 pt-3 pb-3 border-b">
              <input
                type="search"
                autoFocus
                placeholder={searchMode === 'library' ? 'Search your library…' : 'Search TMDB…'}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="overflow-y-auto flex-1 p-5">
              {searchQuery.trim().length < 2 ? (
                <p className="text-sm text-gray-400">Type at least 2 characters to search.</p>
              ) : searchMode === 'tmdb' && (tmdbLoading || debouncedQuery !== searchQuery) ? (
                <p className="text-sm text-gray-400">Searching…</p>
              ) : !hasResults ? (
                <p className="text-sm text-gray-400">No results.</p>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
                  {searchMode === 'library' ? (
                    libraryResults.map((s) => {
                      const wlStatus = watchlistStatusByShowId.get(s.id) ?? null
                      return (
                        <Card key={s.id} className={`overflow-hidden border flex flex-col${wlStatus ? ' ring-2 ring-green-400' : ''}`}>
                          <div className="relative">
                            {s.poster_path ? (
                              <img src={`${TMDB_IMG}${s.poster_path}`} alt={s.title} className="w-full aspect-[2/3] object-cover" loading="lazy" />
                            ) : (
                              <div className="w-full aspect-[2/3] bg-gray-100 flex items-center justify-center text-gray-400 text-xs">No image</div>
                            )}
                            {wlStatus && (
                              <span className={`absolute top-1 right-1 text-xs font-medium px-1.5 py-0.5 rounded ${STATUS_COLOR[wlStatus]}`}>
                                {STATUS_LABEL[wlStatus]}
                              </span>
                            )}
                          </div>
                          <div className="p-2 flex flex-col flex-1">
                            <p className="text-xs font-medium line-clamp-2 flex-1">{s.title}</p>
                            {wlStatus ? (
                              <Link
                                to={`/shows/${s.id}`}
                                className="mt-2 block w-full text-center text-xs bg-green-50 text-green-700 border border-green-300 rounded px-2 py-1 hover:bg-green-100"
                              >
                                View in Library
                              </Link>
                            ) : (
                              <Button
                                onClick={() => handleAddFromLibrary(s.id)}
                                disabled={pendingLibraryIds.has(s.id)}
                                variant="primary"
                                tone="light"
                                size="sm"
                                className="mt-2 w-full"
                              >
                                {pendingLibraryIds.has(s.id) ? 'Adding…' : 'Add'}
                              </Button>
                            )}
                          </div>
                        </Card>
                      )
                    })
                  ) : (
                    tmdbResults.map((r) => {
                      const libraryShow = libraryByTmdbId.get(`${r.id}:${r.media_type ?? 'tv'}`)
                      const wlStatus = libraryShow ? (watchlistStatusByShowId.get(libraryShow.id) ?? null) : null
                      const isPending = pendingTmdbIds.has(r.id) || (!!libraryShow && pendingLibraryIds.has(libraryShow.id))
                      return (
                        <Card key={`${r.id}:${r.media_type}`} className={`overflow-hidden border flex flex-col${wlStatus ? ' ring-2 ring-green-400' : ''}`}>
                          <div className="relative">
                            {r.poster_path ? (
                              <img src={`${TMDB_IMG}${r.poster_path}`} alt={r.name ?? r.title} className="w-full aspect-[2/3] object-cover" loading="lazy" />
                            ) : (
                              <div className="w-full aspect-[2/3] bg-gray-100 flex items-center justify-center text-gray-400 text-xs">No image</div>
                            )}
                            {wlStatus && (
                              <span className={`absolute top-1 right-1 text-xs font-medium px-1.5 py-0.5 rounded ${STATUS_COLOR[wlStatus]}`}>
                                {STATUS_LABEL[wlStatus]}
                              </span>
                            )}
                          </div>
                          <div className="p-2 flex flex-col flex-1">
                            <p className="text-xs font-medium line-clamp-2 flex-1">{r.name ?? r.title}</p>
                            {wlStatus && libraryShow ? (
                              <Link
                                to={`/shows/${libraryShow.id}`}
                                className="mt-2 block w-full text-center text-xs bg-green-50 text-green-700 border border-green-300 rounded px-2 py-1 hover:bg-green-100"
                              >
                                View in Library
                              </Link>
                            ) : (
                              <Button
                                onClick={() => handleAddFromTmdb(r)}
                                disabled={isPending}
                                variant="primary"
                                tone="light"
                                size="sm"
                                className="mt-2 w-full"
                              >
                                {isPending ? 'Adding…' : 'Add'}
                              </Button>
                            )}
                          </div>
                        </Card>
                      )
                    })
                  )}
                </div>
              )}
            </div>
        </Modal>
      )}

      {reorderError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-2">
          Reorder failed: {reorderError}
        </p>
      )}

      {/* Entries table */}
      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-gray-500 text-sm">No watchlist entries yet.</p>
      ) : (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-2 py-2 w-6" />
                <th className="px-4 py-2 text-left w-8">#</th>
                <th className="px-2 py-2 w-48" />
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Up Next</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={orderedEntries.map((e) => e.id)} strategy={verticalListSortingStrategy}>
                <tbody className="divide-y">
                  {orderedEntries.map((e, i) => (
                    <SortableRow
                      key={e.id}
                      entry={e as WatchlistRead}
                      index={i}
                      onDelete={(id) => deleteEntry.mutate(id)}
                      isDeletePending={deleteEntry.isPending}
                      dragEnabled={dragEnabled}
                    />
                  ))}
                </tbody>
              </SortableContext>
            </DndContext>
          </table>
        </Card>
      )}
    </div>
  )
}
