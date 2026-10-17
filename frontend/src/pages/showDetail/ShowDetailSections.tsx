import { WatchlistStatusSelect } from '@/components/WatchlistStatusSelect'
import { QueuePositionSelect, WatchlistToggleButton } from '@/pages/showDetail/WatchlistControls'
import { WatchedProgressBar } from '@/components/WatchedProgressBar'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Menu } from '@/components/ui/Menu'
import { toHostPath } from '@/utils/paths'
import type { FileRead, MediaPaths, ShowRead, WatchlistRead } from '@/types/api'

/**
 * Presentational sections of the ShowDetail page.
 *
 * Every mutation, query and piece of retained state stays in ShowDetail; these
 * components only arrange what they are handed, so request timing and state
 * lifetime are unchanged.
 */

const OCEAN_PILL =
  'px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-900)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/70'

const IN_FLIGHT_MOVIE_STATUSES = ['downloading', 'routing', 'pending', 'discovered']

interface PrimaryActionsProps {
  showId: number
  show: ShowRead
  isMovie: boolean
  episodeCount: number
  allWatched: boolean
  bulkPending: boolean
  patchPending: boolean
  onBulkToggle: () => void
  onToggleTrackMissing: () => void
  watchlistEntry: WatchlistRead | null
  watchlistEntries: WatchlistRead[]
}

/** Watchlist + watched + track-missing buttons shown under the title. */
export function PrimaryActions({
  showId,
  show,
  isMovie,
  episodeCount,
  allWatched,
  bulkPending,
  patchPending,
  onBulkToggle,
  onToggleTrackMissing,
  watchlistEntry,
  watchlistEntries,
}: PrimaryActionsProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap mt-2">
      <WatchlistToggleButton showId={showId} entryId={watchlistEntry?.id ?? null} />
      {!isMovie && episodeCount > 0 && (
        <button
          onClick={onBulkToggle}
          disabled={bulkPending}
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
          onClick={onToggleTrackMissing}
          disabled={patchPending}
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
}

interface SecondaryInfoProps {
  show: ShowRead
  isMovie: boolean
  movieFileCount: number
  episodeCount: number
  watchedCount: number
  trackedCount: number
}

/** Overview, watched progress and tracked-count lines beneath the actions. */
export function SecondaryInfo({
  show,
  isMovie,
  movieFileCount,
  episodeCount,
  watchedCount,
  trackedCount,
}: SecondaryInfoProps) {
  return (
    <>
      {show.overview && (
        <p className="text-sm text-gray-600 dark:text-gray-400 mt-2 max-w-xl">{show.overview}</p>
      )}
      {!isMovie && (
        <WatchedProgressBar
          watched={watchedCount}
          total={episodeCount}
          showLabel
          className="mt-2 max-w-xl"
        />
      )}
      {isMovie ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
          {movieFileCount > 0 ? 'File linked' : 'No file linked'}
        </p>
      ) : (
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
          {trackedCount} / {episodeCount} episodes tracked
        </p>
      )}
    </>
  )
}

interface MaintenanceActionsProps {
  show: ShowRead
  isDeleting: boolean
  hasRssSubscription: boolean
  rssPending: boolean
  rssError: Error | null
  refreshPending: boolean
  refreshError: Error | null
  onRemove: () => void
  onRss: () => void
  onRefreshMetadata: () => void
  onFixMatch: () => void
  onContentType: () => void
  onAliases: () => void
  onImages: () => void
}

/**
 * Right-hand column of actions. Remove, RSS and Refresh Metadata stay visible;
 * the less common ones (fix match, type, aliases, images) are folded into a
 * single "Action" menu so the column doesn't grow with every new action.
 */
export function MaintenanceActions({
  show,
  isDeleting,
  hasRssSubscription,
  rssPending,
  rssError,
  refreshPending,
  refreshError,
  onRemove,
  onRss,
  onRefreshMetadata,
  onFixMatch,
  onContentType,
  onAliases,
  onImages,
}: MaintenanceActionsProps) {
  return (
    <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
      <Button onClick={onRemove} disabled={isDeleting} variant="danger" tone="light" size="sm" className="w-36">
        {isDeleting ? 'Removing…' : 'Remove Show'}
      </Button>
      <button
        onClick={onRss}
        disabled={rssPending}
        className={`w-36 px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
          hasRssSubscription
            ? 'border-green-300 text-green-700 hover:bg-green-50 dark:text-green-300 dark:hover:bg-green-950/40'
            : 'hover:bg-gray-50 dark:hover:bg-gray-800'
        }`}
      >
        {rssPending ? 'Loading…' : hasRssSubscription ? 'Edit RSS' : 'Add RSS'}
      </button>
      <Button
        onClick={onRefreshMetadata}
        disabled={refreshPending}
        variant="secondary"
        tone="light"
        size="sm"
        className="w-36 whitespace-nowrap disabled:opacity-50"
      >
        {refreshPending ? 'Refreshing…' : 'Refresh Metadata'}
      </Button>
      <Menu
        label="Action"
        variant="secondary"
        tone="light"
        size="sm"
        className="w-36"
        items={[
          { label: 'Fix Match', onSelect: onFixMatch },
          { label: show.content_type ? `Type: ${show.content_type}` : 'Set Type', onSelect: onContentType },
          { label: 'Manage Aliases', onSelect: onAliases },
          { label: 'Change Images', onSelect: onImages },
        ]}
      />
      {rssError && (
        <span className="text-xs text-red-600 text-right max-w-[9rem]">{rssError.message}</span>
      )}
      {refreshError && (
        <span className="text-xs text-red-600 text-right max-w-[9rem]">{refreshError.message}</span>
      )}
    </div>
  )
}

/** The "Local path" card with its Edit Path button and saved confirmation. */
export function LocalPathCard({
  localPath,
  mediaPaths,
  saved,
  onEdit,
}: {
  localPath: string | null | undefined
  mediaPaths: MediaPaths | undefined
  saved: boolean
  onEdit: () => void
}) {
  return (
    <Card as="section" padding="md">
      <h2 className="font-semibold mb-1 dark:text-gray-100">Local path</h2>
      {localPath ? (
        <div className="flex items-start justify-between gap-4">
          <p className="font-mono text-sm text-gray-700 dark:text-gray-300 break-all flex-1">
            {mediaPaths ? toHostPath(localPath, mediaPaths) : localPath}
          </p>
          <button
            onClick={onEdit}
            className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800 flex-shrink-0"
          >
            Edit Path
          </button>
        </div>
      ) : (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">Not set</p>
      )}
      {saved && <p className="text-xs text-green-600 dark:text-green-400 mt-1">Saved.</p>}
    </Card>
  )
}

/** The movie-file card: linked files with a Fix Match button once settled. */
export function MovieFileCard({
  movieFiles,
  onScan,
  onFix,
}: {
  movieFiles: FileRead[]
  onScan: () => void
  onFix: () => void
}) {
  return (
    <Card as="section" padding="md">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold dark:text-gray-100">Movie file</h2>
        <button
          onClick={onScan}
          className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
        >
          Scan Local Files
        </button>
      </div>
      {movieFiles.length > 0 ? (
        <div className="divide-y border rounded-lg">
          {movieFiles.map((f) => (
            <div key={f.id} className="flex items-center justify-between px-3 py-2 text-sm gap-3">
              <span className="font-mono text-xs text-gray-600 dark:text-gray-400 truncate">
                {f.original_filename}
              </span>
              <div className="flex items-center gap-3 shrink-0">
                {!IN_FLIGHT_MOVIE_STATUSES.includes(f.status) && (
                  <button onClick={onFix} className={OCEAN_PILL}>
                    Fix Match
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No file linked yet. Use Scan Local Files to link one from this movie&apos;s local path.
        </p>
      )}
    </Card>
  )
}
