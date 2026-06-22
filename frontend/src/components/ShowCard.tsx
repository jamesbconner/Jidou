import { Link } from 'react-router-dom'
import type { ShowList } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w300'

interface Props {
  show: ShowList
}

export function ShowCard({ show }: Props) {
  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
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
