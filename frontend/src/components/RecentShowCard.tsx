import { Card } from '@/components/ui/Card'
import type { RecentShowItem } from '@/types/api'
import type { RecentSort } from '@/hooks/useDashboard'

const TMDB_IMG = '/api/images/w300'

interface Props {
  show: RecentShowItem
  sort: RecentSort
  onClick: (show: RecentShowItem) => void
}

/** A single show card in the dashboard's "Recently Added Shows" carousel. */
export function RecentShowCard({ show, sort, onClick }: Props) {
  // Show whichever date the current sort actually orders by — created_at is
  // a full timestamp, so it's sliced to a date the same way release_date
  // (already a plain date string) is.
  const date = sort === 'tracked' ? show.created_at.slice(0, 10) : show.release_date?.slice(0, 10)
  return (
    <Card
      as="button"
      onClick={() => onClick(show)}
      className="w-40 shrink-0 snap-start overflow-hidden text-left hover:ring-2 hover:ring-indigo-400 transition-shadow"
    >
      {show.poster_path ? (
        <img
          src={`${TMDB_IMG}${show.poster_path}`}
          alt={show.title}
          className="w-full aspect-[2/3] object-cover"
          loading="lazy"
        />
      ) : (
        <div className="w-full aspect-[2/3] bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-400 dark:text-gray-500 text-sm">
          No image
        </div>
      )}
      <div className="p-2 space-y-1">
        <p className="font-semibold text-sm line-clamp-2 leading-tight text-gray-900 dark:text-gray-100">{show.title}</p>
        <div className="flex items-center gap-1.5 flex-wrap">
          {show.content_type && (
            <span className="text-[10px] uppercase tracking-wide bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded">
              {show.content_type}
            </span>
          )}
          {show.vote_average != null && (
            <span className="text-xs text-gray-500 dark:text-gray-400">★ {show.vote_average.toFixed(1)}</span>
          )}
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500">{date ?? '—'}</p>
      </div>
    </Card>
  )
}
