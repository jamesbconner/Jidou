import { Link } from 'react-router'
import { useShow } from '@/hooks/useShows'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import { STATUS_COLOR, STATUS_LABEL } from '@/utils/watchlistStatus'
import type { WatchlistRead, WatchlistStatus } from '@/types/api'

const TMDB_POSTER = '/api/images/w500'

interface Props {
  entry: WatchlistRead
  onClose: () => void
}

/**
 * Quick-look popup opened from a Watchlist row: show metadata plus the
 * "up next" episode, without navigating away to the full Show Details page.
 *
 * `entry.show` (ShowBrief) only carries title/tmdb_id/poster/backdrop, so
 * overview/rating/release date are fetched via the same `useShow` hook the
 * Show Details page uses. `next_up` is already embedded in the watchlist
 * entry (computed server-side) and needs no extra fetch.
 */
export function ShowPreviewModal({ entry, onClose }: Props) {
  const { data: show, isLoading } = useShow(entry.show_id)
  const nextUp = entry.next_up
  const poster = show?.detail_poster_path ?? show?.poster_path ?? entry.show.poster_path
  const tmdbMediaPath = show?.media_type === 'movie' ? 'movie' : 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${tmdbMediaPath}/${entry.show.tmdb_id}`
  const status = entry.status as WatchlistStatus

  return (
    <Modal
      onClose={onClose}
      tone="light"
      maxWidth="xl"
      ariaLabel={`${entry.show.title} details`}
      closeOnBackdropClick
      className="flex flex-col max-h-[85vh]"
    >
      <div className="flex items-center justify-between px-5 py-4 border-b">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 truncate">{entry.show.title}</h2>
        <ModalCloseButton onClose={onClose} leftGap />
      </div>

      <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
        <div className="flex gap-4">
          {poster ? (
            <img
              src={`${TMDB_POSTER}${poster}`}
              alt={entry.show.title}
              className="w-32 aspect-[2/3] rounded-lg object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-32 aspect-[2/3] rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-400 dark:text-gray-500 text-xs flex-shrink-0">
              No image
            </div>
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {show?.release_date?.slice(0, 4)}
              {show?.release_date && ' · '}
              {show?.media_type}
              {show?.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
              {' · '}
              <a
                href={tmdbUrl}
                target="_blank"
                rel="noreferrer"
                className="text-blue-500 dark:text-blue-400 hover:underline"
              >
                TMDB #{entry.show.tmdb_id}
              </a>
            </p>
            <div className="mt-2">
              <Badge color={STATUS_COLOR[status]}>{STATUS_LABEL[status]}</Badge>
            </div>
            {isLoading ? (
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">Loading overview…</p>
            ) : (
              show?.overview && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">{show.overview}</p>
              )
            )}
          </div>
        </div>

        <section>
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Up Next</h3>
          {nextUp ? (
            <div className="border rounded-lg px-3 py-2">
              <p className="font-medium dark:text-gray-200">
                S{String(nextUp.season_number).padStart(2, '0')}E
                {String(nextUp.episode_number).padStart(2, '0')} — {nextUp.name}
                {nextUp.file_tracked && ' ✓'}
              </p>
              {nextUp.air_date && (
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">Airs {nextUp.air_date}</p>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400 dark:text-gray-500 italic">No unwatched episodes.</p>
          )}
        </section>
      </div>

      <div className="flex justify-end gap-2 px-5 py-3 border-t">
        <Button onClick={onClose} variant="secondary" tone="light" size="md">
          Close
        </Button>
        <Link
          to={`/shows/${entry.show_id}`}
          className="btn px-4 py-2 text-sm bg-blue-600 text-white hover:bg-blue-700"
        >
          View Full Show Page
        </Link>
      </div>
    </Modal>
  )
}
