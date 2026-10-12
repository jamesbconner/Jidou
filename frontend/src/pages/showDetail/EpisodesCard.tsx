import { TrackedBadges } from '@/components/TrackedBadges'
import { WatchedToggle } from '@/components/WatchedToggle'
import { MissingEpisodesList } from '@/components/MissingEpisodesList'
import { Card } from '@/components/ui/Card'
import type { EpisodeList, ShowRead } from '@/types/api'

export type EpisodesTab = 'episodes' | 'missing'

/** The slice of a react-query mutation result the card renders. */
interface MutationState {
  isPending: boolean
  isSuccess: boolean
  isError: boolean
  error: Error | null
}

const OCEAN_PILL =
  'px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-900)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/70'

/** Groups episodes by season number (insertion order within a season is kept). */
export function groupBySeason(episodes: EpisodeList[]): Record<number, EpisodeList[]> {
  const bySeason: Record<number, EpisodeList[]> = {}
  for (const ep of episodes) {
    ;(bySeason[ep.season_number] ??= []).push(ep)
  }
  return bySeason
}

/** Last path segment of a Windows- or POSIX-style path. */
function baseName(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

function tabClass(active: boolean): string {
  return `px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
    active
      ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
      : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
  }`
}

/** Filenames of the files tracked against one episode, shown under its title. */
function TrackedFilenames({ ep }: { ep: EpisodeList }) {
  if (!ep.file_tracked) return null
  if (ep.backing_files.length > 0) {
    return (
      <>
        {ep.backing_files.map((bf) => (
          <div key={bf.id} className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">
            {baseName(bf.filename)}
          </div>
        ))}
      </>
    )
  }
  if (!ep.tracked_filename_display) return null
  return (
    <div className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">
      {baseName(ep.tracked_filename_display)}
    </div>
  )
}

interface EpisodeRowProps {
  ep: EpisodeList
  toggleDisabled: boolean
  fixMatchDisabled: boolean
  onToggleWatched: (ep: EpisodeList) => void
  onFix: (ep: EpisodeList, fileId?: number) => void
  onFixEps: (ep: EpisodeList, fileId?: number) => void
  onLinkFile: (ep: EpisodeList) => void
}

function EpisodeRow({
  ep,
  toggleDisabled,
  fixMatchDisabled,
  onToggleWatched,
  onFix,
  onFixEps,
  onLinkFile,
}: EpisodeRowProps) {
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
    <div className="flex items-start justify-between px-3 py-2 text-sm gap-3 dark:text-gray-200">
      <div className="flex items-start gap-2 min-w-0">
        <WatchedToggle
          watched={ep.watched}
          onToggle={() => onToggleWatched(ep)}
          disabled={toggleDisabled}
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
          <TrackedFilenames ep={ep} />
        </div>
      </div>
      {ep.file_tracked ? (
        <TrackedBadges
          ep={ep}
          onFix={(fileId) => onFix(ep, fileId)}
          onFixEps={(fileId) => onFixEps(ep, fileId)}
          fixMatchDisabled={fixMatchDisabled}
        />
      ) : (
        <div className="shrink-0 flex items-center gap-2">
          <button onClick={() => onLinkFile(ep)} className={OCEAN_PILL}>
            Match File
          </button>
        </div>
      )}
    </div>
  )
}

interface SeasonGroupProps extends Omit<EpisodeRowProps, 'ep' | 'toggleDisabled'> {
  season: string
  eps: EpisodeList[]
  bulkPending: boolean
  isEpisodeToggling: (episodeId: number) => boolean
  onToggleSeason: (seasonNumber: number, allWatched: boolean) => void
}

function SeasonGroup({
  season,
  eps,
  bulkPending,
  isEpisodeToggling,
  onToggleSeason,
  ...rowProps
}: SeasonGroupProps) {
  const seasonNumber = Number(season)
  const seasonTracked = eps.filter((e) => e.file_tracked).length
  const seasonWatched = eps.filter((e) => e.watched).length
  const seasonAllWatched = seasonWatched === eps.length
  return (
    <details className="mb-2">
      <summary className="cursor-pointer text-sm font-medium py-1 flex items-center gap-2 dark:text-gray-100">
        <span onClick={(e) => e.preventDefault()}>
          <WatchedToggle
            watched={seasonAllWatched}
            onToggle={() => onToggleSeason(seasonNumber, seasonAllWatched)}
            disabled={bulkPending}
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
          .map((ep) => (
            <EpisodeRow
              key={ep.id}
              ep={ep}
              toggleDisabled={isEpisodeToggling(ep.id)}
              {...rowProps}
            />
          ))}
      </div>
    </details>
  )
}

interface EpisodeToolbarProps {
  showId: number
  show: ShowRead
  syncEpisodes: MutationState & { mutate: (showId: number) => void }
  onScanLocalFiles: () => void
  onEpisodeGroups: () => void
}

/** Sync / scan / grouping buttons shown beside the tabs on the Episodes tab. */
function EpisodeToolbar({
  showId,
  show,
  syncEpisodes,
  onScanLocalFiles,
  onEpisodeGroups,
}: EpisodeToolbarProps) {
  return (
    <div className="flex gap-2 flex-wrap items-center">
      {syncEpisodes.isSuccess && (
        <span className="text-xs text-green-600 dark:text-green-400">Episodes synced</span>
      )}
      {syncEpisodes.isError && (
        <span className="text-xs text-red-600 dark:text-red-400">{syncEpisodes.error?.message}</span>
      )}
      <button
        onClick={() => syncEpisodes.mutate(showId)}
        disabled={syncEpisodes.isPending}
        className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
      >
        {syncEpisodes.isPending ? 'Syncing…' : 'Sync Episodes'}
      </button>
      <button
        onClick={onScanLocalFiles}
        className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        Scan Local Files
      </button>
      <button
        onClick={onEpisodeGroups}
        className="px-3 py-1 text-sm border rounded hover:bg-gray-50 dark:hover:bg-gray-800"
      >
        {show.active_episode_group_id ? 'Change Episode Grouping' : 'Use Alternate Grouping'}
      </button>
    </div>
  )
}

export interface EpisodesCardProps {
  showId: number
  show: ShowRead
  episodes: EpisodeList[]
  today: string | undefined
  missingCount: number
  tab: EpisodesTab
  onTabChange: (tab: EpisodesTab) => void
  syncEpisodes: MutationState & { mutate: (showId: number) => void }
  beginRematch: MutationState
  bulkPending: boolean
  isEpisodeToggling: (episodeId: number) => boolean
  onToggleSeason: (seasonNumber: number, allWatched: boolean) => void
  onToggleWatched: (ep: EpisodeList) => void
  onFix: (ep: EpisodeList, fileId?: number) => void
  onFixEps: (ep: EpisodeList, fileId?: number) => void
  onLinkFile: (ep: EpisodeList) => void
  onScanLocalFiles: () => void
  onEpisodeGroups: () => void
}

/**
 * The tv-show "Episodes / Missing Episodes" card.
 *
 * Purely presentational: the mutations and the selected tab live in ShowDetail
 * (they outlive a tab switch), and arrive here as props and callbacks.
 */
export function EpisodesCard({
  showId,
  show,
  episodes,
  today,
  missingCount,
  tab,
  onTabChange,
  syncEpisodes,
  beginRematch,
  bulkPending,
  isEpisodeToggling,
  onToggleSeason,
  onToggleWatched,
  onFix,
  onFixEps,
  onLinkFile,
  onScanLocalFiles,
  onEpisodeGroups,
}: EpisodesCardProps) {
  const bySeason = groupBySeason(episodes)
  return (
    <Card as="section" padding="md">
      <div className="flex items-center justify-between mb-3 gap-4 flex-wrap">
        <div className="flex border-b -mb-3">
          <button onClick={() => onTabChange('episodes')} className={tabClass(tab === 'episodes')}>
            Episodes ({episodes.length})
          </button>
          <button onClick={() => onTabChange('missing')} className={tabClass(tab === 'missing')}>
            Missing Episodes
            {missingCount > 0 && (
              <span className="ml-2 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded-full px-1.5 py-0.5">
                {missingCount}
              </span>
            )}
          </button>
        </div>
        {tab === 'episodes' && (
          <EpisodeToolbar
            showId={showId}
            show={show}
            syncEpisodes={syncEpisodes}
            onScanLocalFiles={onScanLocalFiles}
            onEpisodeGroups={onEpisodeGroups}
          />
        )}
      </div>
      {tab === 'missing' ? (
        <MissingEpisodesList episodes={episodes} today={today} />
      ) : (
        <>
          {beginRematch.isError && (
            <p className="text-xs text-red-500 dark:text-red-400 mb-2">
              {beginRematch.error?.message}
            </p>
          )}
          {Object.entries(bySeason)
            .sort(([a], [b]) => Number(a) - Number(b))
            .map(([season, eps]) => (
              <SeasonGroup
                key={season}
                season={season}
                eps={eps}
                bulkPending={bulkPending}
                isEpisodeToggling={isEpisodeToggling}
                onToggleSeason={onToggleSeason}
                fixMatchDisabled={beginRematch.isPending}
                onToggleWatched={onToggleWatched}
                onFix={onFix}
                onFixEps={onFixEps}
                onLinkFile={onLinkFile}
              />
            ))}
        </>
      )}
    </Card>
  )
}
