import { Link } from 'react-router-dom'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w185'

// Only the fields this card actually renders — kept narrower than the full
// TmdbResult/DiscoverResult shape so both (which differ in how strictly they
// type overview/vote_average/etc.) can be passed here without friction.
interface CardResult {
  poster_path?: string | null
  name?: string | null
  title?: string | null
}

interface Props {
  result: CardResult
  inLibraryShowId?: number | null
  onAdd: () => void
  addPending: boolean
  addLabel?: string
  subtitle?: string
  onNavigate?: () => void
}

export function TmdbResultCard({
  result,
  inLibraryShowId,
  onAdd,
  addPending,
  addLabel = 'Add',
  subtitle,
  onNavigate,
}: Props) {
  const inLibrary = inLibraryShowId != null

  return (
    <div className={`bg-white rounded-lg shadow overflow-hidden border flex flex-col${inLibrary ? ' ring-2 ring-green-400' : ''}`}>
      <div className="relative">
        {result.poster_path ? (
          <img
            src={`${TMDB_IMG}${result.poster_path}`}
            alt={result.name ?? result.title ?? undefined}
            className="w-full aspect-[2/3] object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full aspect-[2/3] bg-gray-100 flex items-center justify-center text-gray-400 text-xs">
            No image
          </div>
        )}
        {inLibrary && (
          <span className="absolute top-1 right-1 bg-green-500 text-white text-xs font-medium px-1.5 py-0.5 rounded">
            In Library
          </span>
        )}
      </div>
      <div className="p-2 flex flex-col flex-1">
        <p className="text-xs font-medium line-clamp-2 flex-1">{result.name ?? result.title}</p>
        {subtitle && <p className="text-[11px] text-gray-400 mt-0.5 line-clamp-1">{subtitle}</p>}
        {inLibrary && inLibraryShowId ? (
          <Link
            to={`/shows/${inLibraryShowId}`}
            onClick={onNavigate}
            className="mt-2 block w-full text-center text-xs bg-green-50 text-green-700 border border-green-300 rounded px-2 py-1 hover:bg-green-100"
          >
            View in Library
          </Link>
        ) : (
          <button
            onClick={onAdd}
            disabled={addPending}
            className="mt-2 w-full text-xs bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:opacity-50"
          >
            {addPending ? 'Adding…' : addLabel}
          </button>
        )}
      </div>
    </div>
  )
}
