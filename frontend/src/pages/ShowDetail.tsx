import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { arrayMove } from '@dnd-kit/sortable'
import {
  useShow,
  useShowEpisodes,
  useUpdateShowPaths,
  useSyncEpisodes,
  useDeleteShow,
  usePatchShow,
  useSetEpisodeWatched,
  useClearEpisodeWatched,
  useBulkSetEpisodesWatched,
  useBulkClearEpisodesWatched,
} from '@/hooks/useShows'
import { useBeginEpisodeRematch, useFilesByShow } from '@/hooks/useFiles'
import { useRssSubscriptions, useRssFeeds, useEnsureRssStub } from '@/hooks/useRss'
import {
  useWatchlist,
  useCreateWatchlistEntry,
  useDeleteWatchlistEntry,
  useReorderWatchlist,
} from '@/hooks/useWatchlist'
import { WatchlistStatusSelect } from '@/components/WatchlistStatusSelect'
import { RematchModal } from '@/components/RematchModal'
import { FixEpisodeModal } from '@/components/FixEpisodeModal'
import { AssignImportModal } from '@/components/AssignImportModal'
import { LinkFileModal } from '@/components/LinkFileModal'
import { ScanLocalFilesModal } from '@/components/ScanLocalFilesModal'
import { ScanLocalMovieFileModal } from '@/components/ScanLocalMovieFileModal'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { AliasModal } from '@/components/AliasModal'
import { PosterPickerModal } from '@/components/PosterPickerModal'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import { ShowRematchModal } from '@/components/ShowRematchModal'
import { ContentTypeModal } from '@/components/ContentTypeModal'
import { EditPathModal } from '@/components/EditPathModal'
import { TrackedBadges } from '@/components/TrackedBadges'
import { WatchedToggle } from '@/components/WatchedToggle'
import { WatchedProgressBar } from '@/components/WatchedProgressBar'
import { MissingEpisodesList } from '@/components/MissingEpisodesList'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { api } from '@/api/client'
import { toHostPath } from '@/utils/paths'
import { computeMissingEpisodes } from '@/utils/missingEpisodes'
import type {
  EpisodeList,
  FileRead,
  AppConfig,
  RssSubscriptionRead,
  WatchlistRead,
} from '@/types/api'

const TMDB_POSTER = '/api/images/w500'

// ---------------------------------------------------------------------------
// Watchlist controls
// ---------------------------------------------------------------------------

function WatchlistToggleButton({
  showId,
  entryId,
}: {
  showId: number
  entryId: number | null
}) {
  const create = useCreateWatchlistEntry()
  const del = useDeleteWatchlistEntry()
  const pending = create.isPending || del.isPending
  const inWatchlist = entryId != null

  return (
    <button
      onClick={() => (inWatchlist ? del.mutate(entryId) : create.mutate({ show_id: showId }))}
      disabled={pending}
      className={`px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
        inWatchlist
          ? 'border-blue-300 text-blue-700 bg-blue-50 hover:bg-blue-100'
          : 'text-gray-600 hover:bg-gray-50'
      }`}
    >
      {pending ? '…' : inWatchlist ? 'Remove From Watchlist' : 'Add To Watchlist'}
    </button>
  )
}

function QueuePositionSelect({
  entries,
  entryId,
}: {
  entries: WatchlistRead[]
  entryId: number
}) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reorder = useReorderWatchlist()
  const index = entries.findIndex((e) => e.id === entryId)

  if (index === -1) return null

  if (!editing) {
    return (
      <>
        <Badge
          color="bg-gray-100 text-gray-700"
          onClick={() => {
            setError(null)
            setEditing(true)
          }}
          title="Click to change queue position"
        >
          Queue #{index + 1}
        </Badge>
        {error && (
          <span className="text-xs text-red-600" title={error}>
            Reorder failed
          </span>
        )}
      </>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={index}
      onChange={(e) => {
        const newIndex = Number(e.target.value)
        setEditing(false)
        if (newIndex === index) return
        reorder.mutate(arrayMove(entries, index, newIndex), {
          onError: (err) => {
            setError(err instanceof Error ? err.message : 'Failed to reorder')
          },
        })
      }}
      onBlur={() => setEditing(false)}
      className="text-xs border rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {entries.map((_, i) => (
        <option key={i} value={i}>
          #{i + 1}
        </option>
      ))}
    </select>
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
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })
  const { data: episodes = [] } = useShowEpisodes(showId)
  const isMovie = (show?.content_type ?? show?.media_type) === 'movie'
  const { data: movieFiles = [] } = useFilesByShow(showId, isMovie)
  const updatePaths = useUpdateShowPaths(showId)
  const syncEpisodes = useSyncEpisodes()
  const deleteShow = useDeleteShow()
  const beginRematch = useBeginEpisodeRematch()
  const patchShow = usePatchShow()
  const setEpisodeWatched = useSetEpisodeWatched()
  const clearEpisodeWatched = useClearEpisodeWatched()
  const bulkSetWatched = useBulkSetEpisodesWatched()
  const bulkClearWatched = useBulkClearEpisodesWatched()
  const { data: rssSubs = [] } = useRssSubscriptions({ show_id: showId })
  const { data: rssFeeds = [] } = useRssFeeds()
  const ensureRssStub = useEnsureRssStub()
  // TODO: fetches the entire watchlist just to look up this one show (no by-show
  // API filter exists yet). Add a `show_id` filter to GET /watchlist and use it
  // here; keep a lazy full-list fetch (enabled only once this show is confirmed
  // on the watchlist) for the Queue #N position/reorder dropdown.
  const { data: watchlistEntries = [] } = useWatchlist(undefined, 10000)

  const [rematchOpen, setRematchOpen] = useState(false)
  const [pathModalOpen, setPathModalOpen] = useState(false)
  const [contentTypeOpen, setContentTypeOpen] = useState(false)
  const [aliasModalOpen, setAliasModalOpen] = useState(false)
  const [posterModalOpen, setPosterModalOpen] = useState(false)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [fileForRematch, setFileForRematch] = useState<FileRead | null>(null)
  const [fileForFixEps, setFileForFixEps] = useState<FileRead | null>(null)
  const [assignImportEp, setAssignImportEp] = useState<EpisodeList | null>(null)
  const [linkFileEp, setLinkFileEp] = useState<EpisodeList | null>(null)
  const [scanLocalFilesOpen, setScanLocalFilesOpen] = useState(false)
  const [scanLocalMovieFileOpen, setScanLocalMovieFileOpen] = useState(false)
  const [rssModalSub, setRssModalSub] = useState<RssSubscriptionRead | null>(null)
  const [episodesTab, setEpisodesTab] = useState<'episodes' | 'missing'>('episodes')

  useEffect(() => {
    setRematchOpen(false)
    setPathModalOpen(false)
    setContentTypeOpen(false)
    setAliasModalOpen(false)
    setPosterModalOpen(false)
    setDeleteConfirmOpen(false)
    setFileForRematch(null)
    setFileForFixEps(null)
    setAssignImportEp(null)
    setLinkFileEp(null)
    setScanLocalFilesOpen(false)
    setScanLocalMovieFileOpen(false)
    setRssModalSub(null)
    setEpisodesTab('episodes')
    syncEpisodes.reset()
    updatePaths.reset()
    patchShow.reset()
    ensureRssStub.reset()
  }, [showId]) // eslint-disable-line react-hooks/exhaustive-deps

  const existingRssSub =
    rssSubs.length > 0
      ? [...rssSubs].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
      : null

  function handleRssButtonClick() {
    if (existingRssSub) {
      setRssModalSub(existingRssSub)
    } else {
      ensureRssStub.mutate(showId, { onSuccess: (sub) => setRssModalSub(sub) })
    }
  }

  if (isLoading) return <p className="text-gray-400">Loading…</p>
  if (!show) return <p className="text-red-500">Show not found.</p>

  const bySeason: Record<number, typeof episodes> = {}
  for (const ep of episodes) {
    ;(bySeason[ep.season_number] ??= []).push(ep)
  }

  const trackedCount = episodes.filter((e) => e.file_tracked).length
  const watchedCount = episodes.filter((e) => e.watched).length
  const missingCount = computeMissingEpisodes(episodes).reduce((sum, s) => sum + s.missing.length, 0)
  const allWatched = episodes.length > 0 && watchedCount === episodes.length
  const hasImportEps = episodes.some((e) => e.tracked_source === 'import')

  const tmdbMediaPath = show.media_type === 'movie' ? 'movie' : 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${tmdbMediaPath}/${show.tmdb_id}`
  const watchlistEntry = watchlistEntries.find((e) => e.show_id === showId) ?? null

  function handleDelete() {
    setIsDeleting(true)
    deleteShow.mutate(showId, {
      onSuccess: () => navigate('/shows'),
      onSettled: () => setIsDeleting(false),
    })
  }

  function handleSavePath(path: string | null) {
    updatePaths.mutate({ local_path: path }, { onSuccess: () => setPathModalOpen(false) })
  }

  async function handleEpisodeFix(ep: EpisodeList, fileId?: number) {
    try {
      const file = await beginRematch.mutateAsync({ showId, episodeId: ep.id, fileId })
      setFileForFixEps(null)
      setAssignImportEp(null)
      setFileForRematch(file)
    } catch {
      // error surfaced via beginRematch.error — no additional handling needed
    }
  }

  function handleToggleWatched(ep: EpisodeList) {
    if (ep.watched) {
      clearEpisodeWatched.mutate({ showId, episodeId: ep.id })
    } else {
      setEpisodeWatched.mutate({ showId, episodeId: ep.id })
    }
  }

  function handleEpisodeFixEps(ep: EpisodeList, fileId?: number) {
    if (ep.backing_files.length === 0 && (ep.tracked_source === 'import' || !ep.file_tracked)) {
      // Imported or untracked: pure metadata swap via assign-import endpoint.
      setFileForRematch(null)
      setFileForFixEps(null)
      setAssignImportEp(ep)
    } else {
      // Downloaded/backed: begin-rematch → FixEpisodeModal; pass fileId so
      // multi-backed episodes target the chip the user clicked.
      beginRematch
        .mutateAsync({ showId, episodeId: ep.id, fileId })
        .then((file) => {
          setFileForRematch(null)
          setAssignImportEp(null)
          setFileForFixEps(file)
        })
        .catch(() => {})
    }
  }

  return (
    <div className="space-y-8">
      <Link to="/shows" className="text-sm text-blue-600 hover:underline">
        ← Back to Shows
      </Link>

      {/* Header */}
      <div className="flex gap-6">
        {(show.detail_poster_path ?? show.poster_path) && (
          <img
            src={`${TMDB_POSTER}${show.detail_poster_path ?? show.poster_path}`}
            alt={show.title}
            className="w-48 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
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
                {' · '}
                <a
                  href={tmdbUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-500 hover:underline"
                >
                  TMDB #{show.tmdb_id}
                </a>
                {show.content_type && (
                  <span className="ml-2 bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded">
                    {show.content_type}
                  </span>
                )}
              </p>
              <div className="flex items-center gap-2 flex-wrap mt-2">
                <WatchlistToggleButton showId={showId} entryId={watchlistEntry?.id ?? null} />
                {!isMovie && episodes.length > 0 && (
                  <button
                    onClick={() =>
                      allWatched
                        ? bulkClearWatched.mutate({ showId })
                        : bulkSetWatched.mutate({ showId })
                    }
                    disabled={bulkSetWatched.isPending || bulkClearWatched.isPending}
                    className={`px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
                      allWatched
                        ? 'border-green-300 text-green-700 bg-green-50 hover:bg-green-100'
                        : 'text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {allWatched ? 'Mark Unwatched' : 'Mark Watched'}
                  </button>
                )}
                {watchlistEntry && (
                  <>
                    <QueuePositionSelect entries={watchlistEntries} entryId={watchlistEntry.id} />
                    <WatchlistStatusSelect id={watchlistEntry.id} current={watchlistEntry.status} />
                  </>
                )}
              </div>
              {show.overview && (
                <p className="text-sm text-gray-600 mt-2 max-w-xl">{show.overview}</p>
              )}
              {!isMovie && (
                <WatchedProgressBar
                  watched={watchedCount}
                  total={episodes.length}
                  showLabel
                  className="mt-2 max-w-xl"
                />
              )}
              {isMovie ? (
                <p className="text-sm text-gray-500 mt-2">
                  {movieFiles.length > 0 ? 'File linked' : 'No file linked'}
                </p>
              ) : (
                <p className="text-sm text-gray-500 mt-2">
                  {trackedCount} / {episodes.length} episodes tracked
                </p>
              )}
            </div>

            {/* Show-level actions — upper right */}
            <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
              <Button onClick={() => setDeleteConfirmOpen(true)} disabled={isDeleting} variant="danger" tone="light" size="sm" className="w-28">
                {isDeleting ? 'Removing…' : 'Remove Show'}
              </Button>
              <button
                onClick={handleRssButtonClick}
                disabled={ensureRssStub.isPending}
                className={`w-28 px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
                  existingRssSub
                    ? 'border-green-300 text-green-700 hover:bg-green-50'
                    : 'hover:bg-gray-50'
                }`}
              >
                {ensureRssStub.isPending ? 'Loading…' : existingRssSub ? 'Edit RSS' : 'Add RSS'}
              </button>
              <Button onClick={() => setRematchOpen(true)} variant="secondary" tone="light" size="sm" className="w-28">
                Fix Match
              </Button>
              <Button onClick={() => setContentTypeOpen(true)} variant="secondary" tone="light" size="sm" className="w-28">
                {show.content_type ? `Type: ${show.content_type}` : 'Set Type'}
              </Button>
              <Button onClick={() => setAliasModalOpen(true)} variant="secondary" tone="light" size="sm" className="w-28">
                Manage Aliases
              </Button>
              <Button onClick={() => setPosterModalOpen(true)} variant="secondary" tone="light" size="sm" className="w-28">
                Change Poster
              </Button>
              {ensureRssStub.isError && (
                <span className="text-xs text-red-600 text-right max-w-[10rem]">
                  {(ensureRssStub.error as Error).message}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Local path */}
      <Card as="section" padding="md">
        <h2 className="font-semibold mb-1">Local path</h2>
        {show.local_path ? (
          <div className="flex items-start justify-between gap-4">
            <p className="font-mono text-sm text-gray-700 break-all flex-1">
              {config ? toHostPath(show.local_path, config.media_paths) : show.local_path}
            </p>
            <button
              onClick={() => setPathModalOpen(true)}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50 flex-shrink-0"
            >
              Edit Path
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-400 italic">Not set</p>
        )}
        {updatePaths.isSuccess && <p className="text-xs text-green-600 mt-1">Saved.</p>}
      </Card>

      {/* Movie file / Episodes */}
      {isMovie ? (
        <Card as="section" padding="md">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold">Movie file</h2>
            <button
              onClick={() => setScanLocalMovieFileOpen(true)}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
            >
              Scan Local Files
            </button>
          </div>
          {movieFiles.length > 0 ? (
            <div className="divide-y border rounded-lg">
              {movieFiles.map((f) => (
                <div
                  key={f.id}
                  className="flex items-center justify-between px-3 py-2 text-sm gap-3"
                >
                  <span className="font-mono text-xs text-gray-600 truncate">
                    {f.original_filename}
                  </span>
                  <span className="text-xs text-gray-400 shrink-0">{f.status}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400 italic">
              No file linked yet. Use Scan Local Files to link one from this movie&apos;s local
              path.
            </p>
          )}
        </Card>
      ) : (
        <Card as="section" padding="md">
          <div className="flex items-center justify-between mb-3 gap-4 flex-wrap">
            <div className="flex border-b -mb-3">
              <button
                onClick={() => setEpisodesTab('episodes')}
                className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                  episodesTab === 'episodes'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Episodes ({episodes.length})
              </button>
              <button
                onClick={() => setEpisodesTab('missing')}
                className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                  episodesTab === 'missing'
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700'
                }`}
              >
                Missing Episodes
                {missingCount > 0 && (
                  <span className="ml-2 bg-amber-100 text-amber-700 text-xs rounded-full px-1.5 py-0.5">
                    {missingCount}
                  </span>
                )}
              </button>
            </div>
            {episodesTab === 'episodes' && (
              <div className="flex gap-2 flex-wrap items-center">
                <button
                  onClick={() => syncEpisodes.mutate(showId)}
                  disabled={syncEpisodes.isPending}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
                >
                  {syncEpisodes.isPending ? 'Syncing…' : 'Sync Episodes'}
                </button>
                <button
                  onClick={() => setScanLocalFilesOpen(true)}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
                >
                  Scan Local Files
                </button>
                {syncEpisodes.isSuccess && (
                  <span className="text-xs text-green-600">Episodes synced</span>
                )}
                {syncEpisodes.isError && (
                  <span className="text-xs text-red-600">
                    {(syncEpisodes.error as Error).message}
                  </span>
                )}
              </div>
            )}
          </div>
          {episodesTab === 'missing' ? (
            <MissingEpisodesList episodes={episodes} />
          ) : (
            <>
          {beginRematch.isError && (
            <p className="text-xs text-red-500 mb-2">{(beginRematch.error as Error).message}</p>
          )}
          {Object.entries(bySeason)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([season, eps]) => {
              const seasonNumber = Number(season)
              const seasonTracked = eps.filter((e) => e.file_tracked).length
              const seasonWatched = eps.filter((e) => e.watched).length
              const seasonAllWatched = seasonWatched === eps.length
              return (
                <details key={season} className="mb-2">
                  <summary className="cursor-pointer text-sm font-medium py-1 flex items-center gap-2">
                    <span onClick={(e) => e.preventDefault()}>
                      <WatchedToggle
                        watched={seasonAllWatched}
                        onToggle={() => {
                          if (seasonAllWatched) {
                            bulkClearWatched.mutate({ showId, seasonNumber })
                          } else {
                            bulkSetWatched.mutate({ showId, seasonNumber })
                          }
                        }}
                        disabled={bulkSetWatched.isPending || bulkClearWatched.isPending}
                      />
                    </span>
                    <span>
                      Season {season} ({eps.length} episodes)
                    </span>
                    {seasonTracked > 0 && (
                      <span className="text-xs text-green-600">{seasonTracked} tracked</span>
                    )}
                    {seasonWatched > 0 && (
                      <span className="text-xs text-gray-500">{seasonWatched} watched</span>
                    )}
                  </summary>
                  <div className="mt-2 divide-y border rounded-lg">
                    {eps
                      .sort((a, b) => a.episode_number - b.episode_number)
                      .map((ep) => {
                        const header = (
                          <>
                            <span className="text-gray-400 mr-2">{ep.episode_number}.</span>
                            {ep.name}
                            {ep.air_date && (
                              <span className="text-gray-400 ml-2 text-xs">{ep.air_date}</span>
                            )}
                          </>
                        )
                        return (
                        <div
                          key={ep.id}
                          className="flex items-start justify-between px-3 py-2 text-sm gap-3"
                        >
                          <div className="flex items-start gap-2 min-w-0">
                            <WatchedToggle
                              watched={ep.watched}
                              onToggle={() => handleToggleWatched(ep)}
                              disabled={
                                (setEpisodeWatched.isPending &&
                                  setEpisodeWatched.variables?.episodeId === ep.id) ||
                                (clearEpisodeWatched.isPending &&
                                  clearEpisodeWatched.variables?.episodeId === ep.id)
                              }
                            />
                            <div className="min-w-0">
                              {ep.overview ? (
                                <details>
                                  <summary className="cursor-pointer list-none">{header}</summary>
                                  <p className="text-xs text-gray-500 mt-1">{ep.overview}</p>
                                </details>
                              ) : (
                                header
                              )}
                              {ep.file_tracked &&
                                (ep.backing_files.length > 0
                                  ? ep.backing_files.map((bf) => (
                                      <div
                                        key={bf.id}
                                        className="text-xs text-gray-400 font-mono mt-0.5"
                                      >
                                        {bf.filename.replace(/\\/g, '/').split('/').pop() ??
                                          bf.filename}
                                      </div>
                                    ))
                                  : ep.tracked_filename_display && (
                                      <div className="text-xs text-gray-400 font-mono mt-0.5">
                                        {ep.tracked_filename_display.replace(/\\/g, '/').split('/').pop() ??
                                          ep.tracked_filename_display}
                                      </div>
                                    ))}
                            </div>
                          </div>
                          {ep.file_tracked ? (
                            <TrackedBadges
                              ep={ep}
                              onFix={(fileId) => handleEpisodeFix(ep, fileId)}
                              onFixEps={(fileId) => handleEpisodeFixEps(ep, fileId)}
                              fixMatchDisabled={beginRematch.isPending}
                            />
                          ) : (
                            <div className="shrink-0 flex items-center gap-2">
                              <button
                                onClick={() => setLinkFileEp(ep)}
                                className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200"
                              >
                                Match File
                              </button>
                              {hasImportEps && (
                                <button
                                  onClick={() => handleEpisodeFixEps(ep)}
                                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200"
                                >
                                  Fix Eps
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                        )
                      })}
                  </div>
                </details>
              )
            })}
            </>
          )}
        </Card>
      )}

      {/* Modals */}
      {deleteConfirmOpen && (
        <ConfirmDialog
          title="Remove show?"
          description={`Remove "${show.title}" and all its episode data? This cannot be undone.`}
          confirmLabel="Remove"
          danger
          onConfirm={() => { setDeleteConfirmOpen(false); handleDelete() }}
          onCancel={() => setDeleteConfirmOpen(false)}
        />
      )}
      {pathModalOpen && (
        <EditPathModal
          current={show.local_path ?? null}
          onSave={handleSavePath}
          onClose={() => setPathModalOpen(false)}
          isPending={updatePaths.isPending}
        />
      )}
      {rematchOpen && (
        <ShowRematchModal
          key={showId}
          showId={showId}
          currentTmdbId={show.tmdb_id}
          onClose={() => setRematchOpen(false)}
        />
      )}
      {rssModalSub && (
        <SubscriptionEditModal
          sub={rssModalSub}
          feeds={rssFeeds}
          onClose={() => setRssModalSub(null)}
        />
      )}
      {contentTypeOpen && (
        <ContentTypeModal
          key={showId}
          current={show.content_type ?? null}
          onSave={async (value) => {
            try {
              await patchShow.mutateAsync({ id: showId, patch: { content_type: value } })
              setContentTypeOpen(false)
            } catch {
              // error is surfaced via patchShow.error passed to the modal
            }
          }}
          onClose={() => {
            setContentTypeOpen(false)
            patchShow.reset()
          }}
          isPending={patchShow.isPending}
          error={patchShow.error as Error | null}
        />
      )}
      {aliasModalOpen && (
        <AliasModal
          show={show}
          onClose={() => setAliasModalOpen(false)}
        />
      )}
      {posterModalOpen && (
        <PosterPickerModal
          show={show}
          onClose={() => setPosterModalOpen(false)}
        />
      )}
      {fileForRematch && (
        <RematchModal
          file={fileForRematch}
          onClose={() => setFileForRematch(null)}
        />
      )}
      {fileForFixEps && (
        <FixEpisodeModal
          file={fileForFixEps}
          onClose={() => setFileForFixEps(null)}
        />
      )}
      {assignImportEp && (
        <AssignImportModal
          showId={showId}
          episode={assignImportEp}
          onClose={() => setAssignImportEp(null)}
        />
      )}
      {linkFileEp && (
        <LinkFileModal
          showId={showId}
          showLocalPath={show.local_path ?? null}
          episode={linkFileEp}
          onClose={() => setLinkFileEp(null)}
        />
      )}
      {scanLocalFilesOpen && (
        <ScanLocalFilesModal showId={showId} onClose={() => setScanLocalFilesOpen(false)} />
      )}
      {scanLocalMovieFileOpen && (
        <ScanLocalMovieFileModal
          showId={showId}
          onClose={() => setScanLocalMovieFileOpen(false)}
        />
      )}
    </div>
  )
}
