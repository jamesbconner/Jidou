import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  useShow,
  useShowEpisodes,
  useUpdateShowPaths,
  useSyncEpisodes,
  useDeleteShow,
  usePatchShow,
} from '@/hooks/useShows'
import { useBeginEpisodeRematch } from '@/hooks/useFiles'
import { useRssSubscriptions, useRssFeeds, useEnsureRssStub } from '@/hooks/useRss'
import { RematchModal } from '@/components/RematchModal'
import { FixEpisodeModal } from '@/components/FixEpisodeModal'
import { AssignImportModal } from '@/components/AssignImportModal'
import { LinkFileModal } from '@/components/LinkFileModal'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { AliasModal } from '@/components/AliasModal'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import { ShowRematchModal } from '@/components/ShowRematchModal'
import { ContentTypeModal } from '@/components/ContentTypeModal'
import { EditPathModal } from '@/components/EditPathModal'
import { TrackedBadges } from '@/components/TrackedBadges'
import { api } from '@/api/client'
import { toHostPath } from '@/utils/paths'
import type {
  EpisodeList,
  FileRead,
  AppConfig,
  RssSubscriptionRead,
} from '@/types/api'

const TMDB_BACKDROP = 'https://image.tmdb.org/t/p/w500'

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
  const updatePaths = useUpdateShowPaths(showId)
  const syncEpisodes = useSyncEpisodes()
  const deleteShow = useDeleteShow()
  const beginRematch = useBeginEpisodeRematch()
  const patchShow = usePatchShow()
  const { data: rssSubs = [] } = useRssSubscriptions({ show_id: showId })
  const { data: rssFeeds = [] } = useRssFeeds()
  const ensureRssStub = useEnsureRssStub()

  const [rematchOpen, setRematchOpen] = useState(false)
  const [pathModalOpen, setPathModalOpen] = useState(false)
  const [contentTypeOpen, setContentTypeOpen] = useState(false)
  const [aliasModalOpen, setAliasModalOpen] = useState(false)
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [fileForRematch, setFileForRematch] = useState<FileRead | null>(null)
  const [fileForFixEps, setFileForFixEps] = useState<FileRead | null>(null)
  const [assignImportEp, setAssignImportEp] = useState<EpisodeList | null>(null)
  const [linkFileEp, setLinkFileEp] = useState<EpisodeList | null>(null)
  const [rssModalSub, setRssModalSub] = useState<RssSubscriptionRead | null>(null)

  useEffect(() => {
    setRematchOpen(false)
    setPathModalOpen(false)
    setContentTypeOpen(false)
    setAliasModalOpen(false)
    setDeleteConfirmOpen(false)
    setFileForRematch(null)
    setFileForFixEps(null)
    setAssignImportEp(null)
    setLinkFileEp(null)
    setRssModalSub(null)
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
  const hasImportEps = episodes.some((e) => e.tracked_source === 'import')

  const tmdbMediaPath = show.media_type === 'movie' ? 'movie' : 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${tmdbMediaPath}/${show.tmdb_id}`

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

            {/* Destructive action — upper right */}
            <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
              <button
                onClick={() => setDeleteConfirmOpen(true)}
                disabled={isDeleting}
                className="px-3 py-1.5 text-xs border border-red-300 text-red-600 rounded hover:bg-red-50 disabled:opacity-50 whitespace-nowrap"
              >
                {isDeleting ? 'Removing…' : 'Remove Show'}
              </button>
              <span
                className={`px-3 py-1 text-xs rounded whitespace-nowrap cursor-default select-none ${
                  existingRssSub
                    ? 'bg-green-50 text-green-700 border border-green-200'
                    : 'bg-gray-50 text-gray-400 border border-gray-200'
                }`}
              >
                {existingRssSub ? 'In RSS Feed' : 'Not in RSS Feed'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Local path */}
      <section className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-1">Local path</h2>
        {show.local_path ? (
          <p className="font-mono text-sm text-gray-700 break-all">
            {config ? toHostPath(show.local_path, config.media_paths) : show.local_path}
          </p>
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
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {syncEpisodes.isPending ? 'Syncing…' : 'Sync Episodes'}
          </button>
          <button
            onClick={() => setPathModalOpen(true)}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
          >
            Edit Path
          </button>
          <button
            onClick={() => setRematchOpen(true)}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
          >
            Change TMDB Match
          </button>
          <button
            onClick={() => setContentTypeOpen(true)}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
          >
            {show.content_type ? `Content Type: ${show.content_type}` : 'Set Content Type'}
          </button>
          <button
            onClick={() => setAliasModalOpen(true)}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50"
          >
            Manage Aliases
          </button>
          <button
            onClick={handleRssButtonClick}
            disabled={ensureRssStub.isPending}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {ensureRssStub.isPending ? 'Loading…' : existingRssSub ? 'Edit RSS' : 'Add RSS'}
          </button>
          {syncEpisodes.isSuccess && <span className="text-xs text-green-600">Episodes synced</span>}
          {syncEpisodes.isError && (
            <span className="text-xs text-red-600">{(syncEpisodes.error as Error).message}</span>
          )}
          {ensureRssStub.isError && (
            <span className="text-xs text-red-600">{(ensureRssStub.error as Error).message}</span>
          )}
        </div>
      </section>

      {/* Episodes */}
      <section>
        <h2 className="font-semibold mb-3">Episodes ({episodes.length})</h2>
        {beginRematch.isError && (
          <p className="text-xs text-red-500 mb-2">
            {(beginRematch.error as Error).message}
          </p>
        )}
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
                        className="flex items-start justify-between px-3 py-2 text-sm gap-3"
                      >
                        <div className="min-w-0">
                          <span className="text-gray-400 mr-2">{ep.episode_number}.</span>
                          {ep.name}
                          {ep.air_date && (
                            <span className="text-gray-400 ml-2 text-xs">{ep.air_date}</span>
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
                              : ep.tracked_filename && (
                                  <div className="text-xs text-gray-400 font-mono mt-0.5">
                                    {ep.tracked_filename.replace(/\\/g, '/').split('/').pop() ??
                                      ep.tracked_filename}
                                  </div>
                                ))}
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
                              className="text-xs text-blue-600 hover:underline"
                            >
                              Match File
                            </button>
                            {hasImportEps && (
                              <button
                                onClick={() => handleEpisodeFixEps(ep)}
                                className="text-xs text-blue-600 hover:underline"
                              >
                                Fix Eps
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                </div>
              </details>
            )
          })}
      </section>

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
    </div>
  )
}
