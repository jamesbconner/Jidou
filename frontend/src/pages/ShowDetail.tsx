import { useState, useEffect, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  useShow,
  useShowEpisodes,
  useUpdateShowPaths,
  useSyncEpisodes,
  useRematchShow,
  useDeleteShow,
  useSearchShows,
} from '@/hooks/useShows'
import { useFilesByShow, useRematchFile } from '@/hooks/useFiles'
import { FileStatusBadge } from '@/components/FileStatusBadge'
import type { TmdbResult } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w185'
const TMDB_BACKDROP = 'https://image.tmdb.org/t/p/w500'

// ---------------------------------------------------------------------------
// TMDB re-match panel (search UI only — trigger lives in the header)
// ---------------------------------------------------------------------------

function RematchPanel({
  showId,
  currentTmdbId,
  onClose,
}: {
  showId: number
  currentTmdbId: number
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rematch = useRematchShow(showId)

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(query), 300)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query])

  const { data: searchData } = useSearchShows(debouncedQuery)

  function handlePick(r: TmdbResult) {
    if (r.id === currentTmdbId) return
    if (
      !window.confirm(
        `Re-match to "${r.name ?? r.title}"?\n\nThis will replace all episode data for this show.`,
      )
    )
      return
    rematch.mutate(
      { tmdbId: r.id, mediaType: r.media_type ?? 'tv' },
      { onSuccess: () => onClose() },
    )
  }

  return (
    <div className="border rounded-lg p-4 bg-amber-50 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-amber-800">Search for the correct show on TMDB</p>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-700">
          Cancel
        </button>
      </div>
      <input
        type="search"
        placeholder="Search TMDB…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoFocus
        className="border rounded px-2 py-1 text-sm w-full focus:outline-none focus:ring-2 focus:ring-amber-400"
      />
      {rematch.isError && (
        <p className="text-xs text-red-600">{(rematch.error as Error).message}</p>
      )}
      {debouncedQuery.length >= 2 && searchData && searchData.results.length > 0 && (
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
          {searchData.results.slice(0, 12).map((r) => (
            <button
              key={`${r.media_type ?? 'unknown'}-${r.id}`}
              onClick={() => handlePick(r)}
              disabled={rematch.isPending || r.id === currentTmdbId}
              className="text-left bg-white rounded shadow overflow-hidden hover:ring-2 hover:ring-amber-400 disabled:opacity-40 transition"
            >
              {r.poster_path ? (
                <img
                  src={`${TMDB_IMG}${r.poster_path}`}
                  alt={r.name ?? r.title ?? ''}
                  className="w-full h-28 object-cover"
                  loading="lazy"
                />
              ) : (
                <div className="w-full h-28 bg-gray-100 flex items-center justify-center text-gray-400 text-xs">
                  No image
                </div>
              )}
              <div className="p-1">
                <p className="text-xs line-clamp-2 leading-tight">{r.name ?? r.title}</p>
                {r.id === currentTmdbId && (
                  <p className="text-xs text-green-600 font-medium">Current</p>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
      {rematch.isPending && (
        <p className="text-xs text-amber-700">Re-matching… episodes are being synced.</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Edit-path modal
// ---------------------------------------------------------------------------

function EditPathModal({
  current,
  onSave,
  onClose,
  isPending,
}: {
  current: string | null
  onSave: (path: string | null) => void
  onClose: () => void
  isPending: boolean
}) {
  const [draft, setDraft] = useState(current ?? '')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSave(draft.trim() || null)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg mx-4">
        <h3 className="font-semibold mb-4">Edit Local Path</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="border rounded px-3 py-2 text-sm w-full font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="/media/shows/example  or  Z:\media\shows\example"
            autoFocus
          />
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm border rounded hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ShowDetail() {
  const { id } = useParams<{ id: string }>()
  const showId = Number(id)
  const navigate = useNavigate()

  const { data: show, isLoading } = useShow(showId)
  const { data: episodes = [] } = useShowEpisodes(showId)
  const updatePaths = useUpdateShowPaths(showId)
  const syncEpisodes = useSyncEpisodes()
  const deleteShow = useDeleteShow()
  const { data: showFiles = [] } = useFilesByShow(showId)
  const rematchFile = useRematchFile()

  const [rematchOpen, setRematchOpen] = useState(false)
  const [pathModalOpen, setPathModalOpen] = useState(false)

  useEffect(() => {
    setRematchOpen(false)
    syncEpisodes.reset()
    updatePaths.reset()
  }, [showId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (isLoading) return <p className="text-gray-400">Loading…</p>
  if (!show) return <p className="text-red-500">Show not found.</p>

  const bySeason: Record<number, typeof episodes> = {}
  for (const ep of episodes) {
    ;(bySeason[ep.season_number] ??= []).push(ep)
  }

  const trackedCount = episodes.filter((e) => e.file_tracked).length

  const tmdbMediaPath = show.media_type === 'movie' ? 'movie' : 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${tmdbMediaPath}/${show.tmdb_id}`

  function handleDelete() {
    if (window.confirm(`Remove "${show!.title}" and all its episode data? This cannot be undone.`))
      deleteShow.mutate(showId, { onSuccess: () => navigate('/shows') })
  }

  function handleSavePath(path: string | null) {
    updatePaths.mutate({ local_path: path }, { onSuccess: () => setPathModalOpen(false) })
  }

  return (
    <div className="space-y-8">
      <Link to="/shows" className="text-sm text-blue-600 hover:underline">
        ← Back to Shows
      </Link>

      {/* Header */}
      <div className="flex gap-6">
        {show.backdrop_path && (
          <img
            src={`${TMDB_BACKDROP}${show.backdrop_path}`}
            alt={show.title}
            className="w-48 rounded-lg object-cover hidden md:block"
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h1 className="text-2xl font-bold">{show.title}</h1>
              <p className="text-gray-500 text-sm mt-1">
                {show.release_date?.slice(0, 4)}
                {show.release_date && ' · '}
                {show.media_type}
                {show.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
                {show.content_type && (
                  <span className="ml-2 bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded">
                    {show.content_type}
                  </span>
                )}
              </p>
              <a
                href={tmdbUrl}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-blue-500 hover:underline mt-0.5 inline-block"
              >
                TMDB #{show.tmdb_id}
              </a>
              {show.overview && (
                <p className="text-sm text-gray-600 mt-2 max-w-xl">{show.overview}</p>
              )}
              <p className="text-sm text-gray-500 mt-2">
                {trackedCount} / {episodes.length} episodes tracked
              </p>
            </div>

            {/* Rare actions — upper right */}
            <div className="flex flex-col gap-2 items-end flex-shrink-0">
              <button
                onClick={() => setRematchOpen((v) => !v)}
                className="px-3 py-1.5 text-xs border border-amber-400 text-amber-700 rounded hover:bg-amber-50 whitespace-nowrap"
              >
                Change TMDB Match
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteShow.isPending}
                className="px-3 py-1.5 text-xs border border-red-300 text-red-600 rounded hover:bg-red-50 disabled:opacity-50 whitespace-nowrap"
              >
                {deleteShow.isPending ? 'Removing…' : 'Remove Show'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Rematch panel (shown inline below header when open) */}
      {rematchOpen && (
        <RematchPanel
          key={showId}
          showId={showId}
          currentTmdbId={show.tmdb_id}
          onClose={() => setRematchOpen(false)}
        />
      )}

      {/* Local path */}
      <section className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between mb-1">
          <h2 className="font-semibold">Local path</h2>
          <button
            onClick={() => setPathModalOpen(true)}
            className="px-3 py-1 text-xs border rounded hover:bg-gray-50"
          >
            Edit Path
          </button>
        </div>
        {show.local_path ? (
          <p className="font-mono text-sm text-gray-700 break-all">{show.local_path}</p>
        ) : (
          <p className="text-sm text-gray-400 italic">Not set</p>
        )}
        {updatePaths.isSuccess && <p className="text-xs text-green-600 mt-1">Saved.</p>}
      </section>

      {/* Actions */}
      <section className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-3">Actions</h2>
        <div className="flex gap-2 flex-wrap items-center">
          <button
            onClick={() => syncEpisodes.mutate(showId)}
            disabled={syncEpisodes.isPending}
            className="px-3 py-1 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {syncEpisodes.isPending ? 'Syncing…' : 'Sync Episodes'}
          </button>
          {syncEpisodes.isSuccess && <span className="text-xs text-green-600">Episodes synced</span>}
          {syncEpisodes.isError && (
            <span className="text-xs text-red-600">{(syncEpisodes.error as Error).message}</span>
          )}
        </div>
      </section>

      {/* Episodes */}
      <section>
        <h2 className="font-semibold mb-3">Episodes ({episodes.length})</h2>
        {Object.entries(bySeason)
          .sort(([a], [b]) => Number(a) - Number(b))
          .map(([season, eps]) => {
            const seasonTracked = eps.filter((e) => e.file_tracked).length
            return (
              <details key={season} className="mb-2">
                <summary className="cursor-pointer text-sm font-medium py-1 flex items-center gap-2">
                  <span>
                    Season {season} ({eps.length} episodes)
                  </span>
                  {seasonTracked > 0 && (
                    <span className="text-xs text-green-600">{seasonTracked} tracked</span>
                  )}
                </summary>
                <div className="mt-2 divide-y border rounded-lg">
                  {eps
                    .sort((a, b) => a.episode_number - b.episode_number)
                    .map((ep) => (
                      <div
                        key={ep.id}
                        className="flex items-center justify-between px-3 py-2 text-sm"
                      >
                        <span>
                          <span className="text-gray-400 mr-2">{ep.episode_number}.</span>
                          {ep.name}
                          {ep.air_date && (
                            <span className="text-gray-400 ml-2 text-xs">{ep.air_date}</span>
                          )}
                        </span>
                        {ep.file_tracked && (
                          <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
                            Tracked
                          </span>
                        )}
                      </div>
                    ))}
                </div>
              </details>
            )
          })}
      </section>

      {/* Files */}
      {showFiles.length > 0 && (
        <section>
          <h2 className="font-semibold mb-3">Files ({showFiles.length})</h2>
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 text-left">Filename</th>
                  <th className="px-4 py-2 text-left">Status</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y">
                {showFiles.map((f) => (
                  <tr key={f.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-mono text-xs max-w-xs">
                      <div className="truncate">{f.original_filename}</div>
                      {f.error_message && (
                        <div
                          className="text-red-500 truncate mt-0.5"
                          title={f.error_message}
                        >
                          {f.error_message}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <FileStatusBadge status={f.status} />
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => rematchFile.mutate({ id: f.id, payload: {} })}
                        disabled={rematchFile.isPending}
                        className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                      >
                        Re-match
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Edit path modal */}
      {pathModalOpen && (
        <EditPathModal
          current={show.local_path ?? null}
          onSave={handleSavePath}
          onClose={() => setPathModalOpen(false)}
          isPending={updatePaths.isPending}
        />
      )}
    </div>
  )
}
