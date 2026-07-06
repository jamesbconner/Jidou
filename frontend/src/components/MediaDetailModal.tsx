import { Link } from 'react-router-dom'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import type { RecentSort } from '@/hooks/useDashboard'
import type { RecentShowItem, RecentEpisodeItem } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w300'

type MediaItem =
  | { kind: 'show'; show: RecentShowItem; sort: RecentSort }
  | { kind: 'episode'; episode: RecentEpisodeItem; sort: RecentSort }

interface Props {
  item: MediaItem
  onClose: () => void
}

/** Detail popup for a dashboard show or episode card — renders entirely from
 * data already fetched with the carousel, no additional TMDB call needed. */
export function MediaDetailModal({ item, onClose }: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)

  const showId = item.kind === 'show' ? item.show.id : item.episode.show.id
  const image =
    item.kind === 'show'
      ? item.show.poster_path
      : (item.episode.still_path ?? item.episode.show.poster_path)
  const title =
    item.kind === 'show'
      ? item.show.title
      : `${item.episode.show.title} — S${String(item.episode.season_number).padStart(2, '0')}E${String(item.episode.episode_number).padStart(2, '0')}`
  const heading = item.kind === 'episode' ? item.episode.name : item.show.title
  const overview = item.kind === 'show' ? item.show.overview : item.episode.overview
  const voteAverage = item.kind === 'show' ? item.show.vote_average : item.episode.show.vote_average
  const genres = item.kind === 'show' ? item.show.genres : item.episode.show.genres
  const contentType = item.kind === 'show' ? item.show.content_type : item.episode.show.content_type
  const tagline = item.kind === 'show' ? item.show.tagline : null
  // Mirror the card's date logic exactly, so the modal never disagrees with
  // the card that opened it.
  const date =
    item.kind === 'show'
      ? item.sort === 'tracked'
        ? item.show.created_at
        : item.show.release_date
      : item.sort === 'tracked'
        ? item.episode.file_tracked_at
        : item.episode.air_date

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        className="w-full max-w-lg bg-white rounded-lg shadow-xl flex flex-col max-h-[90vh]"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-900 truncate">{title}</h2>
          <button onClick={onClose} className="ml-2 text-gray-400 hover:text-gray-600" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-3">
          <div className="flex gap-4">
            {image ? (
              <img
                src={`${TMDB_IMG}${image}`}
                alt={title}
                className="w-24 h-36 object-cover rounded shrink-0"
              />
            ) : (
              <div className="w-24 h-36 shrink-0 bg-gray-100 rounded flex items-center justify-center text-gray-400 text-xs">
                No image
              </div>
            )}
            <div className="space-y-1.5 min-w-0">
              <p className="font-semibold text-sm">{heading}</p>
              {tagline && <p className="text-xs text-gray-500 italic">{tagline}</p>}
              <div className="flex items-center gap-1.5 flex-wrap text-xs text-gray-500">
                {contentType && (
                  <span className="uppercase tracking-wide bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                    {contentType}
                  </span>
                )}
                {voteAverage != null && <span>★ {voteAverage.toFixed(1)}</span>}
                {date && <span>{date.slice(0, 10)}</span>}
              </div>
              {genres && genres.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {genres.map((g) => (
                    <span key={g.id} className="text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">
                      {g.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {overview && <p className="text-sm text-gray-700">{overview}</p>}

          <Link
            to={`/shows/${showId}`}
            onClick={onClose}
            className="inline-block text-sm text-indigo-600 hover:underline"
          >
            View show →
          </Link>
        </div>
      </div>
    </div>
  )
}
