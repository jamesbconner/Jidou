import { Link } from 'react-router'
import { Modal } from '@/components/ui/Modal'
import type { DiscoverResult, TmdbResult } from '@/types/api'

const TMDB_IMG = '/api/images/w300'

interface Props {
  // DiscoverResult always carries media_type; a plain TMDB search result
  // (TmdbResult, e.g. from the Shows page search modal) may omit it —
  // handled below with a 'tv' fallback, same as the search grid does.
  result: DiscoverResult | TmdbResult
  inLibraryShowId: number | null
  onClose: () => void
  /** Called (instead of onClose) when "View show" is clicked — lets a caller
   * that nests this inside another modal (e.g. the Shows search modal) close
   * that enclosing modal too instead of leaving it open behind the navigation.
   * Defaults to onClose. */
  onNavigate?: () => void
}

/** Detail popup for a Discover-page card or a TMDB search result, mirroring
 * MediaDetailModal's shape. Unlike dashboard items, the result may not be in
 * the library yet, so it links out to TMDB itself rather than assuming a
 * local show record. */
export function DiscoverDetailModal({ result, inLibraryShowId, onClose, onNavigate }: Props) {
  const title = result.name ?? result.title ?? 'Untitled'
  const date = result.release_date ?? result.first_air_date
  const mediaType = result.media_type ?? 'tv'
  const tmdbUrl = `https://www.themoviedb.org/${mediaType}/${result.id}`

  return (
    <Modal onClose={onClose} tone="light" ariaLabel={title} className="flex flex-col max-h-[90vh]">
      <div className="flex items-center justify-between px-5 py-4 border-b">
        <h2 className="font-semibold text-gray-900 truncate">{title}</h2>
        <button onClick={onClose} className="ml-2 text-gray-400 hover:text-gray-600" aria-label="Close">
          ✕
        </button>
      </div>

      <div className="overflow-y-auto flex-1 px-5 py-4 space-y-3">
        <div className="flex gap-4">
          {result.poster_path ? (
            <img
              src={`${TMDB_IMG}${result.poster_path}`}
              alt={title}
              className="w-24 h-36 object-cover rounded shrink-0"
            />
          ) : (
            <div className="w-24 h-36 shrink-0 bg-gray-100 rounded flex items-center justify-center text-gray-400 text-xs">
              No image
            </div>
          )}
          <div className="space-y-1.5 min-w-0">
            <p className="font-semibold text-sm">{title}</p>
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-gray-500">
              <span className="uppercase tracking-wide bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                {mediaType}
              </span>
              {result.vote_average != null && <span>★ {result.vote_average.toFixed(1)}</span>}
              {date && <span>{date.slice(0, 10)}</span>}
            </div>
          </div>
        </div>

        {result.overview && <p className="text-sm text-gray-700">{result.overview}</p>}

        <div className="flex items-center gap-4">
          {inLibraryShowId != null && (
            <Link
              to={`/shows/${inLibraryShowId}`}
              onClick={onNavigate ?? onClose}
              className="inline-block text-sm text-indigo-600 hover:underline"
            >
              View show →
            </Link>
          )}
          <a
            href={tmdbUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-block text-sm text-indigo-600 hover:underline"
          >
            View on TMDB →
          </a>
        </div>
      </div>
    </Modal>
  )
}
