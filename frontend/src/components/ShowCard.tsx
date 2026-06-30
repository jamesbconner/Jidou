import { Link } from 'react-router-dom'
import { DQ_CHECKS } from '@/utils/dqChecks'
import type { ShowList } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w300'

interface Props {
  show: ShowList
  watchlistEntryId?: number | null
  onWatchlistToggle?: (showId: number, watchlistEntryId: number | null) => void
  watchlistPending?: boolean
}

function EyeIcon({ filled }: { filled: boolean }) {
  return filled ? (
    // Solid eye — on watchlist
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
      <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>
    </svg>
  ) : (
    // Outline eye — not on watchlist
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  )
}

export function ShowCard({ show, watchlistEntryId, onWatchlistToggle, watchlistPending = false }: Props) {
  const dqIssues = DQ_CHECKS.filter((c) => c.test(show))
  const inWatchlist = watchlistEntryId != null

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div className="relative">
        <Link to={`/shows/${show.id}`} className="block">
          {show.poster_path ? (
            <img
              src={`${TMDB_IMG}${show.poster_path}`}
              alt={show.title}
              className="w-full h-48 object-cover"
              loading="lazy"
            />
          ) : (
            <div className="w-full h-48 bg-gray-100 flex items-center justify-center text-gray-400 text-sm">
              No image
            </div>
          )}
        </Link>

        {/* Watchlist toggle — upper left */}
        {onWatchlistToggle && (
          <button
            onClick={(e) => {
              e.preventDefault()
              onWatchlistToggle(show.id, watchlistEntryId ?? null)
            }}
            disabled={watchlistPending}
            className={`absolute top-1.5 left-1.5 w-6 h-6 rounded-full flex items-center justify-center shadow transition-colors disabled:opacity-50 disabled:cursor-wait ${
              inWatchlist
                ? 'bg-blue-500 text-white hover:bg-blue-600'
                : 'bg-black/40 text-white hover:bg-black/60'
            }`}
            title={inWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}
          >
            <EyeIcon filled={inWatchlist} />
          </button>
        )}

        {/* DQ badge — upper right */}
        {dqIssues.length > 0 && (
          <span
            className="absolute top-1.5 right-1.5 bg-amber-400 text-white text-xs font-bold w-5 h-5 rounded-full flex items-center justify-center shadow"
            title={dqIssues.map((c) => c.label).join(' · ')}
          >
            !
          </span>
        )}
      </div>
      <div className="p-3">
        <Link to={`/shows/${show.id}`} className="font-semibold text-sm hover:underline line-clamp-2">
          {show.title}
        </Link>
        <p className="text-xs text-gray-500 mt-1">
          {show.release_date?.slice(0, 4) ?? '—'} · {show.media_type}
          {show.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
        </p>
      </div>
    </div>
  )
}
