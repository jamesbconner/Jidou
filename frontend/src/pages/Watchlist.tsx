import { useState, useRef, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useWatchlist, useCreateWatchlistEntry, usePatchWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
import { useShows, useSearchShows, useCreateShow } from '@/hooks/useShows'
import type { WatchlistStatus, ShowList, TmdbResult } from '@/types/api'

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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Watchlist() {
  const [statusFilter, setStatusFilter] = useState<WatchlistStatus | ''>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [searchMode, setSearchMode] = useState<'library' | 'tmdb'>('library')
  // Per-item pending sets so concurrent adds don't clobber each other's loading state.
  const [pendingLibraryIds, setPendingLibraryIds] = useState<Set<number>>(new Set())
  const [pendingTmdbIds, setPendingTmdbIds] = useState<Set<number>>(new Set())

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
  const { data: tmdbData } = useSearchShows(searchMode === 'tmdb' ? debouncedQuery : '')

  const createWatchlistEntry = useCreateWatchlistEntry()
  const createShow = useCreateShow()
  const deleteEntry = useDeleteWatchlistEntry()

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
        release_date: result.first_air_date ?? result.release_date,
      },
      {
        onSuccess: (show) => createWatchlistEntry.mutate({ show_id: show.id }),
        onSettled: () => setPendingTmdbIds((s) => removeShowId(s, result.id)),
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
            {!hasResults ? (
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
                <th className="px-4 py-2 text-left w-8">#</th>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Notes</th>
                <th className="px-4 py-2 text-left">Added</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {entries.map((e, i) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400 text-xs">{i + 1}</td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/shows/${e.show_id}`}
                      className="font-medium hover:underline text-blue-700"
                    >
                      {e.show.title}
                    </Link>
                    <span className="block text-xs text-gray-400">TMDB #{e.show.tmdb_id}</span>
                  </td>
                  <td className="px-4 py-2">
                    <InlineStatusSelect id={e.id} current={e.status} />
                  </td>
                  <td className="px-4 py-2">
                    <InlineNotes id={e.id} notes={e.notes} />
                  </td>
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {new Date(e.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => deleteEntry.mutate(e.id)}
                      disabled={deleteEntry.isPending}
                      className="text-xs text-red-500 hover:underline disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
