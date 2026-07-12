import type { RecentEpisodeItem } from '@/types/api'
import type { RecentSort } from '@/hooks/useDashboard'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w300'

interface Props {
  episode: RecentEpisodeItem
  sort: RecentSort
  onClick: (episode: RecentEpisodeItem) => void
}

/** A single episode card in the dashboard's "Recently Added Episodes" carousel. */
export function RecentEpisodeCard({ episode, sort, onClick }: Props) {
  const image = episode.still_path ?? episode.show.poster_path
  // Episode stills are 16:9 (backdrop-style); the poster fallback is 2:3 —
  // genuinely different source aspect ratios, so the box has to match
  // whichever one is actually being shown rather than a single fixed value.
  const imageAspectClass = episode.still_path ? 'aspect-video' : 'aspect-[2/3]'
  // Show whichever date the current sort actually orders by, rather than
  // always preferring file_tracked_at — with "release" sort selected, the
  // list is ordered by air_date, so the card should reflect that.
  const date = (sort === 'tracked' ? episode.file_tracked_at : episode.air_date)?.slice(0, 10) ?? '—'

  return (
    <button
      onClick={() => onClick(episode)}
      className="w-40 shrink-0 snap-start bg-white rounded-lg shadow overflow-hidden text-left hover:ring-2 hover:ring-indigo-400 transition-shadow"
    >
      {image ? (
        <img
          src={`${TMDB_IMG}${image}`}
          alt={episode.name}
          className={`w-full ${imageAspectClass} object-cover`}
          loading="lazy"
        />
      ) : (
        <div
          className={`w-full ${imageAspectClass} bg-gray-100 flex items-center justify-center text-gray-400 text-sm`}
        >
          No image
        </div>
      )}
      <div className="p-2 space-y-1">
        <p className="text-xs text-gray-500 line-clamp-1">{episode.show.title}</p>
        <p className="font-semibold text-sm line-clamp-2 leading-tight">
          S{String(episode.season_number).padStart(2, '0')}E
          {String(episode.episode_number).padStart(2, '0')} — {episode.name}
        </p>
        <div className="flex items-center gap-1.5 flex-wrap">
          {episode.show.content_type && (
            <span className="text-[10px] uppercase tracking-wide bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
              {episode.show.content_type}
            </span>
          )}
          {episode.show.vote_average != null && (
            <span className="text-xs text-gray-500">★ {episode.show.vote_average.toFixed(1)}</span>
          )}
        </div>
        <p className="text-xs text-gray-400">{date}</p>
      </div>
    </button>
  )
}
