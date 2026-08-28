import { Link } from 'react-router'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'

const TMDB_IMG = '/api/images/w185'

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
  /** When set, the whole card opens a detail view (e.g. a metadata modal). */
  onCardClick?: () => void
}

export function TmdbResultCard({
  result,
  inLibraryShowId,
  onAdd,
  addPending,
  addLabel = 'Add',
  subtitle,
  onNavigate,
  onCardClick,
}: Props) {
  const inLibrary = inLibraryShowId != null

  return (
    <Card
      onClick={onCardClick}
      className={`h-full flex flex-col overflow-hidden border${inLibrary ? ' ring-2 ring-green-400' : ''}${onCardClick ? ' cursor-pointer hover:ring-2 hover:ring-[var(--color-ocean-400)] transition-shadow' : ''}`}
    >
      <div className="relative">
        {result.poster_path ? (
          <img
            src={`${TMDB_IMG}${result.poster_path}`}
            alt={result.name ?? result.title ?? ''}
            className="w-full aspect-[2/3] object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full aspect-[2/3] bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-400 dark:text-gray-500 text-xs">
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
        <p className="text-xs font-medium line-clamp-2 flex-1 text-gray-900 dark:text-gray-100">{result.name ?? result.title}</p>
        {subtitle && <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5 line-clamp-1">{subtitle}</p>}
        {inLibrary && inLibraryShowId ? (
          <Link
            to={`/shows/${inLibraryShowId}`}
            onClick={(e) => {
              e.stopPropagation()
              onNavigate?.()
            }}
            className="mt-2 block w-full text-center text-xs bg-green-50 text-green-700 border border-green-300 dark:bg-green-950/40 dark:text-green-300 dark:border-green-800 rounded px-2 py-1 hover:bg-green-100 dark:hover:bg-green-900/40"
          >
            View in Library
          </Link>
        ) : (
          <Button
            onClick={(e) => {
              e.stopPropagation()
              onAdd()
            }}
            disabled={addPending}
            variant="primary"
            tone="light"
            size="sm"
            className="mt-2 w-full"
          >
            {addPending ? 'Adding…' : addLabel}
          </Button>
        )}
      </div>
    </Card>
  )
}
