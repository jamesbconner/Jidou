import { Card } from '@/components/ui/Card'
import type { RecentEpisodeItem } from '@/types/api'
import type { RecentSort } from '@/hooks/useDashboard'

const TMDB_IMG = '/api/images/w300'

interface Props {
  episode: RecentEpisodeItem
  sort: RecentSort
  preferPosters: boolean
  onClick: (episode: RecentEpisodeItem) => void
}

/** A single episode card in the dashboard's "Recently Added Episodes" carousel. */
export function RecentEpisodeCard({ episode, sort, preferPosters, onClick }: Props) {
  // With preferPosters on, every card uses the show poster (falling back to
  // the still only when no poster exists) so the carousel reads as visually
  // uniform, at the cost of episode-specific artwork for shows that have it.
  const image = preferPosters
    ? (episode.show.poster_path ?? episode.still_path)
    : (episode.still_path ?? episode.show.poster_path)
  // Episode stills are 16:9 (backdrop-style); the poster fallback is 2:3 —
  // genuinely different source aspect ratios, so the box has to match
  // whichever one is actually being shown rather than a single fixed value.
  // preferPosters pins the box to the poster ratio regardless of which image
  // ends up rendered, which is the whole point of the "uniform" setting.
  const imageAspectClass = preferPosters
    ? 'aspect-[2/3]'
    : episode.still_path
      ? 'aspect-video'
      : 'aspect-[2/3]'
  // Show whichever date the current sort actually orders by, rather than
  // always preferring file_tracked_at — with "release" sort selected, the
  // list is ordered by air_date, so the card should reflect that.
  const date = (sort === 'tracked' ? episode.file_tracked_at : episode.air_date)?.slice(0, 10) ?? '—'

  return (
    <Card
      as="button"
      onClick={() => onClick(episode)}
      className="w-40 shrink-0 snap-start overflow-hidden text-left hover:ring-2 hover:ring-indigo-400 transition-shadow"
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
          className={`w-full ${imageAspectClass} bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-400 dark:text-gray-500 text-sm`}
        >
          No image
        </div>
      )}
      <div className="p-2 space-y-1">
        <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-1">{episode.show.title}</p>
        <p className="font-semibold text-sm line-clamp-2 leading-tight text-gray-900 dark:text-gray-100">
          S{String(episode.season_number).padStart(2, '0')}E
          {String(episode.episode_number).padStart(2, '0')} — {episode.name}
        </p>
        <div className="flex items-center gap-1.5 flex-wrap">
          {episode.show.content_type && (
            <span className="text-[10px] uppercase tracking-wide bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded">
              {episode.show.content_type}
            </span>
          )}
          {episode.show.vote_average != null && (
            <span className="text-xs text-gray-500 dark:text-gray-400">★ {episode.show.vote_average.toFixed(1)}</span>
          )}
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500">{date}</p>
      </div>
    </Card>
  )
}
