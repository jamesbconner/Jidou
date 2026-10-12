import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router'
import {
  useUpdateShowPaths,
  useSyncEpisodes,
  useDeleteShow,
  usePatchShow,
  useSetEpisodeWatched,
  useClearEpisodeWatched,
  useBulkSetEpisodesWatched,
  useBulkClearEpisodesWatched,
} from '@/hooks/useShows'
import { useBeginEpisodeRematch } from '@/hooks/useFiles'
import { useEnsureRssStub } from '@/hooks/useRss'
import { SimilarTitlesSection } from '@/components/SimilarTitlesSection'
import { ShowDetailHeader } from '@/components/ShowDetailHeader'
import { useBannerStyle } from '@/hooks/useBannerStyle'
import { ShowDetailModals } from '@/pages/showDetail/ShowDetailModals'
import type { ShowDetailModal } from '@/pages/showDetail/modalState'
import { useShowDetailData } from '@/pages/showDetail/useShowDetailData'
import { EpisodesCard, type EpisodesTab } from '@/pages/showDetail/EpisodesCard'
import {
  LocalPathCard,
  MaintenanceActions,
  MovieFileCard,
  PrimaryActions,
  SecondaryInfo,
} from '@/pages/showDetail/ShowDetailSections'
import { episodeStats } from '@/pages/showDetail/episodeStats'
import type { ContentType, EpisodeList } from '@/types/api'

const TMDB_POSTER = '/api/images/w500'

export default function ShowDetail() {
  const { id } = useParams<{ id: string }>()
  const showId = Number(id)
  const navigate = useNavigate()

  const {
    show,
    episodes,
    movieFiles,
    config,
    rssSubs,
    rssFeeds,
    watchlistEntry,
    watchlistEntries,
    isMovie,
    isLoading,
  } = useShowDetailData(showId)
  const updatePaths = useUpdateShowPaths(showId)
  const syncEpisodes = useSyncEpisodes()
  const deleteShow = useDeleteShow()
  const beginRematch = useBeginEpisodeRematch()
  const patchShow = usePatchShow()
  const setEpisodeWatched = useSetEpisodeWatched()
  const clearEpisodeWatched = useClearEpisodeWatched()
  const bulkSetWatched = useBulkSetEpisodesWatched()
  const bulkClearWatched = useBulkClearEpisodesWatched()
  const ensureRssStub = useEnsureRssStub()

  const [modal, setModal] = useState<ShowDetailModal | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [episodesTab, setEpisodesTab] = useState<EpisodesTab>('episodes')
  const [bannerStyle] = useBannerStyle()

  // Resets the modal selection, the tab and other local UI state plus 4 react-query
  // mutation .reset() calls when navigating to a different show — React
  // Router doesn't remount this component on a :id-only route change, so
  // there's no single call site to fold this into. The documented
  // alternative (key={showId} on the route element to force a remount) is
  // a routing-level change beyond this component's scope; calling
  // mutation .reset() during render would also be its own impurity, worse
  // than the one this rule flags.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setModal(null)
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

  // Async completions (a request the user started earlier) must not replace a
  // modal the user has since opened: keep the open one untouched and drop the
  // late one; the user can click again. User-click paths use plain setModal.
  function openModalIfIdle(next: ShowDetailModal) {
    setModal((current) => (current === null ? next : current))
  }

  function handleRssButtonClick() {
    if (existingRssSub) {
      setModal({ kind: 'rssSubscription', subscription: existingRssSub })
    } else {
      ensureRssStub.mutate(showId, { onSuccess: (sub) => openModalIfIdle({ kind: 'rssSubscription', subscription: sub }) })
    }
  }

  if (isLoading) return <p className="text-gray-400 dark:text-gray-500">Loading…</p>
  if (!show) return <p className="text-red-500 dark:text-red-400">Show not found.</p>

  const { trackedCount, watchedCount, missingCount, allWatched } = episodeStats(
    episodes,
    show.track_missing_episodes,
    config?.today,
  )

  const tmdbMediaPath = show.media_type === 'movie' ? 'movie' : 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${tmdbMediaPath}/${show.tmdb_id}`

  // Async completions close their own modal only; if the user has since moved
  // to a different modal, that one must stay open (as with the old per-modal flags).
  function closeModalIfKind(kind: ShowDetailModal['kind']) {
    setModal((current) => (current?.kind === kind ? null : current))
  }

  async function handleSaveContentType(value: ContentType | null) {
    try {
      await patchShow.mutateAsync({ id: showId, patch: { content_type: value } })
      closeModalIfKind('contentType')
    } catch {
      // error is surfaced via patchShow.error passed to the modal
    }
  }

  function handleDelete() {
    setIsDeleting(true)
    deleteShow.mutate(showId, {
      onSuccess: () => navigate('/shows'),
      onSettled: () => setIsDeleting(false),
    })
  }

  function handleSavePath(path: string | null) {
    updatePaths.mutate({ local_path: path }, { onSuccess: () => closeModalIfKind('path') })
  }

  async function handleEpisodeFix(ep: EpisodeList, fileId?: number) {
    try {
      const file = await beginRematch.mutateAsync({ showId, episodeId: ep.id, fileId })
      openModalIfIdle({ kind: 'fileRematch', file })
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
      setModal({ kind: 'assignImport', episode: ep })
    } else {
      // Downloaded/backed: begin-rematch → FixEpisodeModal; pass fileId so
      // multi-backed episodes target the chip the user clicked.
      beginRematch
        .mutateAsync({ showId, episodeId: ep.id, fileId })
        .then((file) => {
          openModalIfIdle({ kind: 'fileFixEps', file })
        })
        .catch(() => {})
    }
  }

  function handleToggleSeason(seasonNumber: number, seasonAllWatched: boolean) {
    if (seasonAllWatched) {
      bulkClearWatched.mutate({ showId, seasonNumber })
    } else {
      bulkSetWatched.mutate({ showId, seasonNumber })
    }
  }

  const bulkPending = bulkSetWatched.isPending || bulkClearWatched.isPending

  const posterPath = show.detail_poster_path ?? show.poster_path
  const posterSrc = posterPath ? `${TMDB_POSTER}${posterPath}` : null

  // Built here (they touch page mutation hooks) and handed to <ShowDetailHeader>,
  // which arranges them per the chosen banner style.
  const primaryActions = (
    <PrimaryActions
      showId={showId}
      show={show}
      isMovie={isMovie}
      episodeCount={episodes.length}
      allWatched={allWatched}
      bulkPending={bulkPending}
      patchPending={patchShow.isPending}
      onBulkToggle={() =>
        allWatched ? bulkClearWatched.mutate({ showId }) : bulkSetWatched.mutate({ showId })
      }
      onToggleTrackMissing={() =>
        patchShow.mutate({
          id: showId,
          patch: { track_missing_episodes: !show.track_missing_episodes },
        })
      }
      watchlistEntry={watchlistEntry}
      watchlistEntries={watchlistEntries}
    />
  )

  const secondaryInfo = (
    <SecondaryInfo
      show={show}
      isMovie={isMovie}
      movieFileCount={movieFiles.length}
      episodeCount={episodes.length}
      watchedCount={watchedCount}
      trackedCount={trackedCount}
    />
  )

  const maintenanceActions = (
    <MaintenanceActions
      show={show}
      isDeleting={isDeleting}
      hasRssSubscription={existingRssSub != null}
      rssPending={ensureRssStub.isPending}
      rssError={ensureRssStub.isError ? (ensureRssStub.error as Error) : null}
      onRemove={() => setModal({ kind: 'deleteConfirm' })}
      onRss={handleRssButtonClick}
      onFixMatch={() => setModal({ kind: 'rematch' })}
      onContentType={() => setModal({ kind: 'contentType' })}
      onAliases={() => setModal({ kind: 'aliases' })}
      onImages={() => setModal({ kind: 'image' })}
    />
  )

  return (
    // -mt-8 cancels Layout's py-8 so the banner sits flush under the navbar.
    <div className="-mt-8 space-y-8">
      {/* Banner style is a browser-local preference set on the Settings page. */}
      <ShowDetailHeader
        show={show}
        style={bannerStyle}
        posterSrc={posterSrc}
        tmdbUrl={tmdbUrl}
        primaryActions={primaryActions}
        secondaryInfo={secondaryInfo}
        maintenanceActions={maintenanceActions}
      />

      <LocalPathCard
        localPath={show.local_path}
        mediaPaths={config?.media_paths}
        saved={updatePaths.isSuccess}
        onEdit={() => setModal({ kind: 'path' })}
      />

      {isMovie ? (
        <MovieFileCard
          movieFiles={movieFiles}
          onScan={() => setModal({ kind: 'scanLocalMovieFile' })}
          onFix={() => setModal({ kind: 'fixMovieFile' })}
        />
      ) : (
        <EpisodesCard
          showId={showId}
          show={show}
          episodes={episodes}
          today={config?.today}
          missingCount={missingCount}
          tab={episodesTab}
          onTabChange={setEpisodesTab}
          syncEpisodes={syncEpisodes}
          beginRematch={beginRematch}
          bulkPending={bulkPending}
          isEpisodeToggling={(episodeId) =>
            (setEpisodeWatched.isPending && setEpisodeWatched.variables?.episodeId === episodeId) ||
            (clearEpisodeWatched.isPending && clearEpisodeWatched.variables?.episodeId === episodeId)
          }
          onToggleSeason={handleToggleSeason}
          onToggleWatched={handleToggleWatched}
          onFix={handleEpisodeFix}
          onFixEps={handleEpisodeFixEps}
          onLinkFile={(episode) => setModal({ kind: 'linkFile', episode })}
          onScanLocalFiles={() => setModal({ kind: 'scanLocalFiles' })}
          onEpisodeGroups={() => setModal({ kind: 'episodeGroups' })}
        />
      )}

      <SimilarTitlesSection showId={showId} />

      <ShowDetailModals
        show={show}
        modal={modal}
        onClose={() => setModal(null)}
        rssFeeds={rssFeeds}
        onConfirmDelete={() => {
          setModal(null)
          handleDelete()
        }}
        onSavePath={handleSavePath}
        isSavingPath={updatePaths.isPending}
        onSaveContentType={handleSaveContentType}
        onResetContentType={patchShow.reset}
        isSavingContentType={patchShow.isPending}
        contentTypeError={patchShow.error as Error | null}
      />
    </div>
  )
}
