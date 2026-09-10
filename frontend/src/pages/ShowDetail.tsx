import { useState, useEffect, type ReactNode } from 'react'
import { useParams, Link, useNavigate } from 'react-router'
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
import { EpisodeGroupPickerModal } from '@/components/EpisodeGroupPickerModal'
import { ContentTypeModal } from '@/components/ContentTypeModal'
import { EditPathModal } from '@/components/EditPathModal'
import { TrackedBadges } from '@/components/TrackedBadges'
import { WatchedToggle } from '@/components/WatchedToggle'
import { WatchedProgressBar } from '@/components/WatchedProgressBar'
import { MissingEpisodesList } from '@/components/MissingEpisodesList'
import { SimilarTitlesSection } from '@/components/SimilarTitlesSection'
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
// Prototype: banner backdrop on the show detail page.
const TMDB_BACKDROP = '/api/images/w1280'
const BANNER_VARIANTS = ['hero', 'strip', 'hybrid', 'compact', 'framed', 'contain', 'full'] as const
type BannerVariant = (typeof BANNER_VARIANTS)[number]

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
          ? 'border-[var(--color-ocean-300)] text-[var(--color-ocean-700)] bg-[var(--color-ocean-50)] hover:bg-[var(--color-ocean-100)] dark:bg-[var(--color-ocean-950)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/40'
          : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800'
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
          color="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
          onClick={() => {
            setError(null)
            setEditing(true)
          }}
          title="Click to change queue position"
        >
          Queue #{index + 1}
        </Badge>
        {error && (
          <span className="text-xs text-red-600 dark:text-red-400" title={error}>
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
  const [episodeGroupModalOpen, setEpisodeGroupModalOpen] = useState(false)
  const [scanLocalMovieFileOpen, setScanLocalMovieFileOpen] = useState(false)
  const [fixMovieFileOpen, setFixMovieFileOpen] = useState(false)
  const [rssModalSub, setRssModalSub] = useState<RssSubscriptionRead | null>(null)
  const [episodesTab, setEpisodesTab] = useState<'episodes' | 'missing'>('episodes')
  // Prototype: compare banner treatments live. Persists via localStorage and
  // across show navigation; seedable via ?banner=<variant>&tint=1.
  const [bannerVariant, setBannerVariant] = useState<BannerVariant>(() => {
    const q = new URLSearchParams(window.location.search).get('banner')
    if (q && (BANNER_VARIANTS as readonly string[]).includes(q)) return q as BannerVariant
    try {
      const s = localStorage.getItem('jidou.banner.variant')
      if (s && (BANNER_VARIANTS as readonly string[]).includes(s)) return s as BannerVariant
    } catch {
      /* localStorage unavailable */
    }
    return 'hero'
  })
  const [bannerTint, setBannerTint] = useState<boolean>(() => {
    const q = new URLSearchParams(window.location.search).get('tint')
    if (q === '1') return true
    if (q === '0') return false
    try {
      return localStorage.getItem('jidou.banner.tint') === '1'
    } catch {
      return false
    }
  })
  const chooseBannerVariant = (v: BannerVariant) => {
    setBannerVariant(v)
    try {
      localStorage.setItem('jidou.banner.variant', v)
    } catch {
      /* localStorage unavailable */
    }
  }
  const toggleBannerTint = () => {
    setBannerTint((t) => {
      try {
        localStorage.setItem('jidou.banner.tint', t ? '0' : '1')
      } catch {
        /* localStorage unavailable */
      }
      return !t
    })
  }

  // Resets ~13 independent pieces of local UI state plus 4 react-query
  // mutation .reset() calls when navigating to a different show — React
  // Router doesn't remount this component on a :id-only route change, so
  // there's no single call site to fold this into. The documented
  // alternative (key={showId} on the route element to force a remount) is
  // a routing-level change beyond this component's scope; calling
  // mutation .reset() during render would also be its own impurity, worse
  // than the one this rule flags.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
    setEpisodeGroupModalOpen(false)
    setScanLocalMovieFileOpen(false)
    setFixMovieFileOpen(false)
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

  if (isLoading) return <p className="text-gray-400 dark:text-gray-500">Loading…</p>
  if (!show) return <p className="text-red-500 dark:text-red-400">Show not found.</p>

  const bySeason: Record<number, typeof episodes> = {}
  for (const ep of episodes) {
    ;(bySeason[ep.season_number] ??= []).push(ep)
  }

  const trackedCount = episodes.filter((e) => e.file_tracked).length
  const watchedCount = episodes.filter((e) => e.watched).length
  const missingCount = show.track_missing_episodes
    ? (
        config?.today
          ? computeMissingEpisodes(episodes, config.today)
          : computeMissingEpisodes(episodes)
      ).reduce((sum, s) => sum + s.missing.length, 0)
    : 0
  const allWatched = episodes.length > 0 && watchedCount === episodes.length

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

  const posterPath = show.detail_poster_path ?? show.poster_path
  const posterSrc = posterPath ? `${TMDB_POSTER}${posterPath}` : null

  // Extracted so the plain header and the prototype hero banner can share them.
  const primaryActions = (
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
              ? 'border-green-300 text-green-700 bg-green-50 hover:bg-green-100 dark:bg-green-950/40 dark:text-green-300 dark:hover:bg-green-900/40'
              : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800'
          }`}
        >
          {allWatched ? 'Mark Unwatched' : 'Mark Watched'}
        </button>
      )}
      {!isMovie && (
        <button
          onClick={() =>
            patchShow.mutate({
              id: showId,
              patch: { track_missing_episodes: !show.track_missing_episodes },
            })
          }
          disabled={patchShow.isPending}
          className={`px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
            !show.track_missing_episodes
              ? 'border-amber-300 text-amber-700 bg-amber-50 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-300 dark:hover:bg-amber-900/40'
              : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800'
          }`}
        >
          {show.track_missing_episodes ? 'Ignore Missing Eps' : 'Track Missing Eps'}
        </button>
      )}
      {watchlistEntry && (
        <>
          <QueuePositionSelect entries={watchlistEntries} entryId={watchlistEntry.id} />
          <WatchlistStatusSelect id={watchlistEntry.id} current={watchlistEntry.status} />
        </>
      )}
    </div>
  )

  const secondaryInfo = (
    <>
      {show.overview && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2 max-w-xl">{show.overview}</p>
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
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
          {movieFiles.length > 0 ? 'File linked' : 'No file linked'}
        </p>
      ) : (
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
          {trackedCount} / {episodes.length} episodes tracked
        </p>
      )}
    </>
  )

  const maintenanceActions = (
    <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
      <Button onClick={() => setDeleteConfirmOpen(true)} disabled={isDeleting} variant="danger" tone="light" size="sm" className="w-28">
        {isDeleting ? 'Removing…' : 'Remove Show'}
      </Button>
      <button
        onClick={handleRssButtonClick}
        disabled={ensureRssStub.isPending}
        className={`w-28 px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
          existingRssSub
            ? 'border-green-300 text-green-700 hover:bg-green-50 dark:text-green-300 dark:hover:bg-green-950/40'
            : 'hover:bg-gray-50 dark:hover:bg-gray-800'
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
  )

  // --- Header treatments (prototype) -----------------------------------
  // Shared pieces so the variants below stay consistent and DRY.
  const backdropImg = (className: string) => (
    <img src={`${TMDB_BACKDROP}${show.backdrop_path}`} alt="" loading="lazy" className={className} />
  )

  // Year · type · ★ rating · TMDB link · content-type chip. `onImage` picks
  // light colours for overlaying on a backdrop.
  const metaLine = (onImage: boolean) => (
    <p className={`text-sm mt-1 ${onImage ? 'text-white/80' : 'text-gray-500 dark:text-gray-400'}`}>
      {show.release_date?.slice(0, 4)}
      {show.release_date && ' · '}
      {show.media_type}
      {show.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
      {' · '}
      <a
        href={tmdbUrl}
        target="_blank"
        rel="noreferrer"
        className={`hover:underline ${
          onImage
            ? 'text-[var(--color-ocean-300)]'
            : 'text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)]'
        }`}
      >
        TMDB #{show.tmdb_id}
      </a>
      {show.content_type && (
        <span
          className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
            onImage
              ? 'bg-white/15 text-white'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'
          }`}
        >
          {show.content_type}
        </span>
      )}
    </p>
  )

  // Frosted restyle of primaryActions for use over imagery.
  const overlayActions = (
    <div className="mt-2 [&_button]:!border-white/30 [&_button]:!bg-white/10 [&_button]:!text-white [&_button]:backdrop-blur-sm [&_button:hover]:!bg-white/20">
      {primaryActions}
    </div>
  )

  // Every variant's backdrop routes through this so the ocean-tint modifier
  // is one code path.
  const backdropBox = (
    boxClassName: string,
    opts: { imgClassName?: string; scrim?: ReactNode; children?: ReactNode } = {},
  ) => (
    <div className={`relative overflow-hidden ${boxClassName}`}>
      {backdropImg(
        `absolute inset-0 h-full w-full ${bannerTint ? 'saturate-[0.35]' : ''} ${
          opts.imgClassName ?? 'object-cover'
        }`,
      )}
      {opts.scrim}
      {bannerTint && (
        <div className="pointer-events-none absolute inset-0 bg-[var(--color-ocean-900)]/45 mix-blend-multiply" />
      )}
      {opts.children != null && <div className="relative">{opts.children}</div>}
    </div>
  )

  const infoBelow = (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">{secondaryInfo}</div>
      {maintenanceActions}
    </div>
  )

  // `plainHeader` — the pre-banner layout; no-backdrop fallback and reused by
  // strip / full.
  const plainHeader = (
    <div className="flex gap-6">
      {posterSrc && (
        <img
          src={posterSrc}
          alt={show.title}
          className="w-48 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold dark:text-gray-100">{show.title}</h1>
            {metaLine(false)}
            {primaryActions}
            {secondaryInfo}
          </div>
          {maintenanceActions}
        </div>
      </div>
    </div>
  )

  // A — hero: full-width backdrop + dark gradient; poster/title/actions overlaid.
  const heroHeader = (
    <div className="space-y-6">
      {backdropBox('rounded-xl min-h-[22rem]', {
        scrim: (
          <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/45 to-black/10" />
        ),
        children: (
          <div className="flex gap-6 p-6 pt-40 sm:pt-56">
            {posterSrc && (
              <img
                src={posterSrc}
                alt={show.title}
                className="w-32 sm:w-44 aspect-[2/3] self-end rounded-lg object-cover shadow-2xl ring-1 ring-black/20"
              />
            )}
            <div className="flex-1 min-w-0 self-end">
              <h1 className="text-3xl font-bold text-white drop-shadow">{show.title}</h1>
              {metaLine(true)}
              {overlayActions}
            </div>
          </div>
        ),
      })}
      {infoBelow}
    </div>
  )

  // B — strip: cropped backdrop band above the unchanged plain header.
  const stripHeader = (
    <div className="space-y-6">
      {backdropBox('-mx-6 h-44 sm:h-56', {
        scrim: <div className="absolute inset-0 bg-gradient-to-t from-black/25 to-transparent" />,
      })}
      {plainHeader}
    </div>
  )

  // C — hybrid: band with title overlaid, poster overhangs the bottom edge,
  // the rest on normal background (Plex / Trakt profile look).
  const hybridHeader = (
    <div>
      {backdropBox('-mx-6 h-52 sm:h-64', {
        scrim: (
          <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/25 to-transparent" />
        ),
        children: (
          <div className="flex h-52 sm:h-64 items-end p-6">
            <div className="w-32 sm:w-40 shrink-0" />
            <div className="ml-5 min-w-0 pb-1">
              <h1 className="text-2xl sm:text-3xl font-bold text-white drop-shadow">{show.title}</h1>
              {metaLine(true)}
            </div>
          </div>
        ),
      })}
      <div className="flex gap-5 -mt-14 sm:-mt-20">
        {posterSrc && (
          <img
            src={posterSrc}
            alt={show.title}
            className="relative w-32 sm:w-40 aspect-[2/3] shrink-0 rounded-lg object-cover shadow-xl ring-2 ring-white/10"
          />
        )}
        <div className="flex-1 min-w-0 flex items-start justify-between gap-4 pt-16 sm:pt-24">
          <div className="min-w-0">
            {primaryActions}
            {secondaryInfo}
          </div>
          {maintenanceActions}
        </div>
      </div>
    </div>
  )

  // D — compact: height-capped hero, strong scrim, frosted buttons.
  const compactHeader = (
    <div className="space-y-6">
      {backdropBox('rounded-xl h-64 sm:h-72', {
        scrim: (
          <div className="absolute inset-0 bg-gradient-to-t from-black via-black/60 to-black/10" />
        ),
        children: (
          <div className="flex h-64 sm:h-72 gap-5 p-5 pt-32 sm:pt-40">
            {posterSrc && (
              <img
                src={posterSrc}
                alt={show.title}
                className="w-28 sm:w-36 aspect-[2/3] self-end rounded-lg object-cover shadow-xl ring-1 ring-black/20"
              />
            )}
            <div className="flex-1 min-w-0 self-end">
              <h1 className="text-2xl font-bold text-white drop-shadow">{show.title}</h1>
              {metaLine(true)}
              {overlayActions}
            </div>
          </div>
        ),
      })}
      {infoBelow}
    </div>
  )

  // E — framed: no overlay; a contained backdrop card beside a plain header.
  const framedHeader = (
    <div className="flex gap-6">
      {posterSrc && (
        <img
          src={posterSrc}
          alt={show.title}
          className="w-44 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-bold dark:text-gray-100">{show.title}</h1>
            {metaLine(false)}
            {primaryActions}
            {secondaryInfo}
          </div>
          <div className="hidden lg:block w-[46%] max-w-md shrink-0">
            {backdropBox('aspect-video rounded-xl ring-1 ring-black/10 dark:ring-white/10')}
          </div>
        </div>
        <div className="mt-4 flex justify-end">{maintenanceActions}</div>
      </div>
    </div>
  )

  // F — contain: whole 16:9 frame always visible (blurred fill + sharp contain).
  const containHeader = (
    <div className="space-y-6">
      {backdropBox('-mx-6 aspect-video bg-black', {
        imgClassName: 'object-cover blur-2xl scale-110 opacity-50',
        scrim: (
          <>
            {backdropImg('absolute inset-0 h-full w-full object-contain')}
            <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/45 to-transparent p-6 pt-20">
              <h1 className="text-2xl sm:text-3xl font-bold text-white drop-shadow">{show.title}</h1>
              {metaLine(true)}
              {overlayActions}
            </div>
          </>
        ),
      })}
      <div className="flex gap-6">
        {posterSrc && (
          <img
            src={posterSrc}
            alt={show.title}
            className="w-44 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
          />
        )}
        <div className="flex-1 min-w-0">{infoBelow}</div>
      </div>
    </div>
  )

  // G — full: whole uncropped backdrop at true 16:9, then the plain header.
  const fullHeader = (
    <div className="space-y-6">
      {backdropBox('-mx-6 aspect-video bg-black', { imgClassName: 'object-contain' })}
      {plainHeader}
    </div>
  )

  const bannerHeaders: Record<BannerVariant, ReactNode> = {
    hero: heroHeader,
    strip: stripHeader,
    hybrid: hybridHeader,
    compact: compactHeader,
    framed: framedHeader,
    contain: containHeader,
    full: fullHeader,
  }
  const bannerHeader = show.backdrop_path ? bannerHeaders[bannerVariant] : plainHeader

  return (
    <div className="space-y-8">
      <Link to="/shows" className="text-sm text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline">
        ← Back to Shows
      </Link>

      {show.backdrop_path && (
        <div className="fixed bottom-3 left-3 z-50 flex max-w-[calc(100vw-1.5rem)] flex-wrap items-center gap-1 rounded-lg border border-gray-300 bg-white/90 p-1 text-xs shadow-lg backdrop-blur dark:border-gray-700 dark:bg-gray-900/90">
          <span className="px-1 text-gray-400">banner</span>
          {BANNER_VARIANTS.map((v) => (
            <button
              key={v}
              onClick={() => chooseBannerVariant(v)}
              className={`rounded px-2 py-1 ${
                bannerVariant === v
                  ? 'bg-[var(--color-ocean-600)] text-white'
                  : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
              }`}
            >
              {v}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-gray-300 dark:bg-gray-700" />
          <button
            onClick={toggleBannerTint}
            className={`rounded px-2 py-1 ${
              bannerTint
                ? 'bg-[var(--color-ocean-600)] text-white'
                : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
            }`}
          >
            tint
          </button>
        </div>
      )}

      {/* Header — prototype: banner treatment chosen via the bottom-left control */}
      {bannerHeader}

      {/* Local path */}
      <Card as="section" padding="md">
        <h2 className="font-semibold mb-1 dark:text-gray-100">Local path</h2>
        {show.local_path ? (
          <div className="flex items-start justify-between gap-4">
            <p className="font-mono text-sm text-gray-700 dark:text-gray-300 break-all flex-1">
              {config ? toHostPath(show.local_path, config.media_paths) : show.local_path}
            </p>
            <button
              onClick={() => setPathModalOpen(true)}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800 flex-shrink-0"
            >
              Edit Path
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">Not set</p>
        )}
        {updatePaths.isSuccess && <p className="text-xs text-green-600 dark:text-green-400 mt-1">Saved.</p>}
      </Card>

      {/* Movie file / Episodes */}
      {isMovie ? (
        <Card as="section" padding="md">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold dark:text-gray-100">Movie file</h2>
            <button
              onClick={() => setScanLocalMovieFileOpen(true)}
              className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
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
                  <span className="font-mono text-xs text-gray-600 dark:text-gray-400 truncate">
                    {f.original_filename}
                  </span>
                  <div className="flex items-center gap-3 shrink-0">
                    {!['downloading', 'routing', 'pending', 'discovered'].includes(f.status) && (
                      <button
                        onClick={() => setFixMovieFileOpen(true)}
                        className="px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-900)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/70"
                      >
                        Fix Match
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic">
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
                    ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
                }`}
              >
                Episodes ({episodes.length})
              </button>
              <button
                onClick={() => setEpisodesTab('missing')}
                className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                  episodesTab === 'missing'
                    ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
                    : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
                }`}
              >
                Missing Episodes
                {missingCount > 0 && (
                  <span className="ml-2 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded-full px-1.5 py-0.5">
                    {missingCount}
                  </span>
                )}
              </button>
            </div>
            {episodesTab === 'episodes' && (
              <div className="flex gap-2 flex-wrap items-center">
                {syncEpisodes.isSuccess && (
                  <span className="text-xs text-green-600 dark:text-green-400">Episodes synced</span>
                )}
                {syncEpisodes.isError && (
                  <span className="text-xs text-red-600 dark:text-red-400">
                    {(syncEpisodes.error as Error).message}
                  </span>
                )}
                <button
                  onClick={() => syncEpisodes.mutate(showId)}
                  disabled={syncEpisodes.isPending}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
                >
                  {syncEpisodes.isPending ? 'Syncing…' : 'Sync Episodes'}
                </button>
                <button
                  onClick={() => setScanLocalFilesOpen(true)}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  Scan Local Files
                </button>
                <button
                  onClick={() => setEpisodeGroupModalOpen(true)}
                  className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
                >
                  {show.active_episode_group_id ? 'Change Episode Grouping' : 'Use Alternate Grouping'}
                </button>
              </div>
            )}
          </div>
          {episodesTab === 'missing' ? (
            <MissingEpisodesList episodes={episodes} today={config?.today} />
          ) : (
            <>
          {beginRematch.isError && (
            <p className="text-xs text-red-500 dark:text-red-400 mb-2">{(beginRematch.error as Error).message}</p>
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
                  <summary className="cursor-pointer text-sm font-medium py-1 flex items-center gap-2 dark:text-gray-100">
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
                      <span className="text-xs text-green-600 dark:text-green-400">{seasonTracked} tracked</span>
                    )}
                    {seasonWatched > 0 && (
                      <span className="text-xs text-gray-500 dark:text-gray-400">{seasonWatched} watched</span>
                    )}
                  </summary>
                  <div className="mt-2 divide-y border rounded-lg">
                    {eps
                      .sort((a, b) => a.episode_number - b.episode_number)
                      .map((ep) => {
                        const header = (
                          <>
                            <span className="text-gray-400 dark:text-gray-500 mr-2">{ep.episode_number}.</span>
                            {ep.name}
                            {ep.air_date && (
                              <span className="text-gray-400 dark:text-gray-500 ml-2 text-xs">{ep.air_date}</span>
                            )}
                          </>
                        )
                        return (
                        <div
                          key={ep.id}
                          className="flex items-start justify-between px-3 py-2 text-sm gap-3 dark:text-gray-200"
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
                                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{ep.overview}</p>
                                </details>
                              ) : (
                                header
                              )}
                              {ep.file_tracked &&
                                (ep.backing_files.length > 0
                                  ? ep.backing_files.map((bf) => (
                                      <div
                                        key={bf.id}
                                        className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5"
                                      >
                                        {bf.filename.replace(/\\/g, '/').split('/').pop() ??
                                          bf.filename}
                                      </div>
                                    ))
                                  : ep.tracked_filename_display && (
                                      <div className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">
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
                                className="px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-900)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/70"
                              >
                                Match File
                              </button>
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

      <SimilarTitlesSection showId={showId} />

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
      {episodeGroupModalOpen && (
        <EpisodeGroupPickerModal show={show} onClose={() => setEpisodeGroupModalOpen(false)} />
      )}
      {scanLocalMovieFileOpen && (
        <ScanLocalMovieFileModal
          showId={showId}
          onClose={() => setScanLocalMovieFileOpen(false)}
        />
      )}
      {fixMovieFileOpen && (
        <ScanLocalMovieFileModal
          showId={showId}
          replace
          onClose={() => setFixMovieFileOpen(false)}
        />
      )}
    </div>
  )
}
