import { useState, useRef, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  DndContext,
  closestCenter,
  PointerSensor,
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
import { useWatchlist, useCreateWatchlistEntry, usePatchWatchlistEntry, useDeleteWatchlistEntry, useReorderWatchlist } from '@/hooks/useWatchlist'
import { useShows, useSearchShows, useCreateShow } from '@/hooks/useShows'
import type { WatchlistStatus, WatchlistRead, ShowList, TmdbResult } from '@/types/api'

const STATUS_OPTIONS: WatchlistStatus[] = ['planned', 'watching', 'completed', 'on_hold', 'dropped']

const STATUS_LABEL: Record<WatchlistStatus, string> = {
  planned: 'Planned',
  watching: 'Watching',
  completed: 'Completed',
  on_hold: 'On Hold',
  dropped: 'Dropped',
}

const STATUS_COLOR: Record<WatchlistStatus, string> = {
  planned: 'bg-gray-100 text-gray-700',
  watching: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  on_hold: 'bg-yellow-100 text-yellow-700',
  dropped: 'bg-red-100 text-red-700',
}

const TMDB_IMG = 'https://image.tmdb.org/t/p/w92'

function InlineStatusSelect({ id, current }: { id: number; current: WatchlistStatus }) {
  const [editing, setEditing] = useState(false)
  const pendingRef = useRef<WatchlistStatus>(current)
  const patch = usePatchWatchlistEntry()

  if (!editing) {
    return (
      <button
        onClick={() => { pendingRef.current = current; setEditing(true) }}
        className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_COLOR[current]} hover:opacity-80`}
        title="Click to change status"
      >
        {STATUS_LABEL[current]}
      </button>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={current}
      onChange={(e) => { pendingRef.current = e.target.value as WatchlistStatus }}
      onBlur={() => {
        setEditing(false)
        if (pendingRef.current !== current) patch.mutate({ id, update: { status: pendingRef.current } })
      }}
      className="text-xs border rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>{STATUS_LABEL[s]}</option>
      ))}
    </select>
  )
}

function InlineNotes({ id, notes }: { id: number; notes: string | null }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(notes ?? '')
  const cancelRef = useRef(false)
  const patch = usePatchWatchlistEntry()

  function commit() {
    if (cancelRef.current) { cancelRef.current = false; return }
    setEditing(false)
    const trimmed = value.trim()
    const next = trimmed === '' ? null : trimmed
    if (next !== notes) patch.mutate({ id, update: { notes: next } })
  }

  if (!editing) {
    return (
      <button
        onClick={() => { cancelRef.current = false; setValue(notes ?? ''); setEditing(true) }}
        className="text-left text-gray-500 hover:text-blue-600 hover:underline max-w-[12rem] truncate block"
        title={notes ?? 'Click to add notes'}
      >
        {notes ?? '—'}
      </button>
    )
  }

  return (
    <input
      type="text"
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') { cancelRef.current = true; setValue(notes ?? ''); setEditing(false) }
      }}
      className="border rounded px-1 py-0.5 text-xs w-36 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  )
}

// ─── Search result row ────────────────────────────────────────────────────────

interface SearchResultRowProps {
  posterPath: string | null
  title: string
  year: string | undefined
  libraryShowId: number | null
  watchlistStatus: WatchlistStatus | null
  onAdd: () => void
  isPending: boolean
}

function SearchResultRow({
  posterPath, title, year, libraryShowId, watchlistStatus, onAdd, isPending,
}: SearchResultRowProps) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50">
      {posterPath ? (
        <img src={`${TMDB_IMG}${posterPath}`} alt={title} className="w-8 h-12 object-cover rounded flex-shrink-0" />
      ) : (
        <div className="w-8 h-12 bg-gray-200 rounded flex-shrink-0" />
      )}
      <div className="flex-1 min-w-0">
        {libraryShowId ? (
          <Link to={`/shows/${libraryShowId}`} className="text-sm font-medium hover:underline text-blue-700 truncate block">
            {title}
          </Link>
        ) : (
          <span className="text-sm font-medium truncate block">{title}</span>
        )}
        <span className="text-xs text-gray-400">{year ?? '—'}</span>
      </div>
      <div className="flex-shrink-0">
        {watchlistStatus ? (
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_COLOR[watchlistStatus]}`}>
            {STATUS_LABEL[watchlistStatus]}
          </span>
        ) : (
          <button
            onClick={onAdd}
            disabled={isPending}
            className="text-xs px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {isPending ? 'Adding…' : 'Add'}
          </button>
        )}
      </div>
    </div>
  )
}

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
  }

  return (
    <tr ref={setNodeRef} style={style} {...attributes} className="hover:bg-gray-50">
      <td
        {...(dragEnabled ? listeners : {})}
        className={`px-2 py-2 ${dragEnabled ? 'text-gray-300 hover:text-gray-500 cursor-grab active:cursor-grabbing' : 'text-gray-200 cursor-not-allowed'}`}
        title={dragEnabled ? 'Drag to reorder' : 'Clear status filter to reorder'}
      >
        <GripIcon />
      </td>
      <td className="px-4 py-2 text-gray-400 text-xs">{index + 1}</td>
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
        <InlineStatusSelect id={entry.id} current={entry.status as WatchlistStatus} />
      </td>
      <td className="px-4 py-2">
        <InlineNotes id={entry.id} notes={entry.notes} />
      </td>
      <td className="px-4 py-2 text-gray-400 text-xs">
        {new Date(entry.created_at).toLocaleDateString()}
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
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [searchMode, setSearchMode] = useState<'library' | 'tmdb'>('library')
  // Per-item pending sets so concurrent adds don't clobber each other's loading state.
  const [pendingLibraryIds, setPendingLibraryIds] = useState<Set<number>>(new Set())
  const [pendingTmdbIds, setPendingTmdbIds] = useState<Set<number>>(new Set())
  const [orderedEntries, setOrderedEntries] = useState<WatchlistRead[]>([])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [searchQuery])

  const { data: entries = [], isLoading } = useWatchlist(statusFilter || undefined)
  // Unfiltered full list for search cross-reference — independent of the status filter and
  // the default limit=50 that powers the table, so search badges are always accurate.
  const { data: allEntries = [] } = useWatchlist(undefined, 10000)
  const { data: allShows = [] } = useShows('title_asc', 10000)
  const { data: tmdbData, isLoading: tmdbLoading } = useSearchShows(searchMode === 'tmdb' ? debouncedQuery : '')

  const createWatchlistEntry = useCreateWatchlistEntry()
  const createShow = useCreateShow()
  const deleteEntry = useDeleteWatchlistEntry()
  const reorderWatchlist = useReorderWatchlist()

  // Reordering within a filtered view would assign 1-based positions to a subset,
  // colliding with hidden entries' positions after the filter is cleared.
  const dragEnabled = statusFilter === ''

  useEffect(() => {
    // Merge server data into the current drag order: preserve the user's ordering
    // for entries that still exist, drop removed entries (deletes, filter changes),
    // and append any newly added entries at the end. This handles concurrent
    // mutations (status/notes/delete) correctly even while a reorder is in flight.
    setOrderedEntries((prev) => {
      const serverMap = new Map((entries as WatchlistRead[]).map((e) => [e.id, e]))
      const kept = prev.filter((e) => serverMap.has(e.id)).map((e) => serverMap.get(e.id)!)
      const keptIds = new Set(kept.map((e) => e.id))
      const added = (entries as WatchlistRead[]).filter((e) => !keptIds.has(e.id))
      return [...kept, ...added]
    })
  }, [entries])

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    // Drop rapid successive drags while a prior batch is in flight to prevent
    // interleaved PATCHes writing inconsistent positions to the server.
    if (reorderWatchlist.isPending) return
    const oldIndex = orderedEntries.findIndex((e) => e.id === active.id)
    const newIndex = orderedEntries.findIndex((e) => e.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = arrayMove(orderedEntries, oldIndex, newIndex)
    setOrderedEntries(reordered)
    reorderWatchlist.mutate(reordered)
  }

  // Map show_id → watchlist status for result-row lookup (uses full unfiltered list)
  const watchlistStatusByShowId = useMemo(
    () => new Map(allEntries.map((e) => [e.show_id, e.status as WatchlistStatus])),
    [allEntries],
  )

  // Map tmdb_id → library ShowList for TMDB result cross-reference
  const libraryByTmdbId = useMemo(
    () => new Map(allShows.map((s) => [s.tmdb_id, s])),
    [allShows],
  )

  const libraryResults: ShowList[] = useMemo(() => {
    if (!debouncedQuery.trim() || searchMode !== 'library') return []
    const q = debouncedQuery.toLowerCase()
    return allShows.filter((s) => s.title.toLowerCase().includes(q)).slice(0, 8)
  }, [allShows, debouncedQuery, searchMode])

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
    const existing = libraryByTmdbId.get(result.id)
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
    createShow.mutate(
      {
        tmdb_id: result.id,
        title: result.name ?? result.title ?? 'Unknown',
        media_type: result.media_type ?? 'tv',
        overview: result.overview,
        poster_path: result.poster_path,
        backdrop_path: result.backdrop_path,
        vote_average: result.vote_average,
        vote_count: result.vote_count,
        original_language: result.original_language,
        genre_ids: result.genre_ids ?? null,
        origin_country: result.origin_country ?? null,
        release_date: result.first_air_date ?? result.release_date,
      },
      {
        onSuccess: (show) => createWatchlistEntry.mutate(
          { show_id: show.id },
          { onSettled: () => setPendingTmdbIds((s) => removeShowId(s, result.id)) },
        ),
        onError: () => setPendingTmdbIds((s) => removeShowId(s, result.id)),
      },
    )
  }

  const showSearchResults = debouncedQuery.trim().length >= 2
  const hasResults = searchMode === 'library' ? libraryResults.length > 0 : tmdbResults.length > 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Watchlist</h1>
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
      </div>

      <p className="text-sm text-gray-500">
        Keep track of shows you want to watch, are currently watching, or have finished.
      </p>

      {/* Add show search */}
      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder={searchMode === 'library' ? 'Search your library…' : 'Search TMDB…'}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none flex-shrink-0">
            <span className={searchMode === 'library' ? 'font-medium text-blue-600' : 'text-gray-400'}>Library</span>
            <button
              role="switch"
              aria-checked={searchMode === 'tmdb'}
              onClick={() => setSearchMode((m) => m === 'library' ? 'tmdb' : 'library')}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                searchMode === 'tmdb' ? 'bg-blue-600' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                  searchMode === 'tmdb' ? 'translate-x-4' : 'translate-x-1'
                }`}
              />
            </button>
            <span className={searchMode === 'tmdb' ? 'font-medium text-blue-600' : 'text-gray-400'}>TMDB</span>
          </label>
        </div>

        {showSearchResults && (
          <div className="border rounded-lg divide-y overflow-hidden">
            {searchMode === 'tmdb' && tmdbLoading ? (
              <p className="px-3 py-2 text-sm text-gray-400">Searching…</p>
            ) : !hasResults ? (
              <p className="px-3 py-2 text-sm text-gray-400">No results.</p>
            ) : searchMode === 'library' ? (
              libraryResults.map((s) => (
                <SearchResultRow
                  key={s.id}
                  posterPath={s.poster_path ?? null}
                  title={s.title}
                  year={s.release_date?.slice(0, 4)}
                  libraryShowId={s.id}
                  watchlistStatus={watchlistStatusByShowId.get(s.id) ?? null}
                  onAdd={() => handleAddFromLibrary(s.id)}
                  isPending={pendingLibraryIds.has(s.id)}
                />
              ))
            ) : (
              tmdbResults.map((r) => {
                const libraryShow = libraryByTmdbId.get(r.id)
                const wlStatus = libraryShow ? (watchlistStatusByShowId.get(libraryShow.id) ?? null) : null
                return (
                  <SearchResultRow
                    key={`${r.id}:${r.media_type}`}
                    posterPath={r.poster_path ?? null}
                    title={r.name ?? r.title ?? 'Unknown'}
                    year={(r.first_air_date ?? r.release_date)?.slice(0, 4)}
                    libraryShowId={libraryShow?.id ?? null}
                    watchlistStatus={wlStatus}
                    onAdd={() => handleAddFromTmdb(r)}
                    isPending={pendingTmdbIds.has(r.id) || (!!libraryShow && pendingLibraryIds.has(libraryShow.id))}
                  />
                )
              })
            )}
          </div>
        )}
      </div>

      {/* Entries table */}
      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-gray-500 text-sm">No watchlist entries yet.</p>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-2 py-2 w-6" />
                <th className="px-4 py-2 text-left w-8">#</th>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Notes</th>
                <th className="px-4 py-2 text-left">Added</th>
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
        </div>
      )}
    </div>
  )
}
