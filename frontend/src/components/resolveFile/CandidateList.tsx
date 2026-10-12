import type { TmdbSuggestion } from '@/types/api'
import type { Candidate, SearchMode } from './useResolveCandidates'
import { year } from './year'

const TMDB_IMAGE_BASE = '/api/images/w185'

interface Props {
  mode: SearchMode
  candidates: Candidate[]
  isLoading: boolean
  error: unknown
  selected: TmdbSuggestion | null
  onSelect: (suggestion: TmdbSuggestion) => void
}

/**
 * The shared TMDB results grid of ResolveFileModal: loading, per-mode error,
 * empty state and the poster cards. Purely presentational so every search mode
 * renders through one grid while the modal keeps ownership of the queries.
 */
export function CandidateList({ mode, candidates, isLoading, error, selected, onSelect }: Props) {
  return (
    <div className="space-y-2">
      {isLoading && <div className="text-xs text-zinc-500 py-2">Loading suggestions…</div>}
      {!isLoading && mode === 'suggestions' && error != null && (
        <div className="text-xs text-red-400 py-2">
          {error instanceof Error ? error.message : 'Failed to load suggestions'}
        </div>
      )}
      {!isLoading && mode === 'tmdb_id' && error != null && (
        <div className="text-xs text-red-400 py-2">
          {error instanceof Error ? error.message : 'Failed to look up TMDB ID'}
        </div>
      )}
      {!isLoading && error == null && candidates.length === 0 && (
        <div className="text-xs text-zinc-500 py-2">No results found.</div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {candidates.map((c) => {
          const r = c.tmdb
          if (!r) return null
          return (
            <button
              key={c.key}
              onClick={() => onSelect(r)}
              className={`flex flex-col rounded border text-left overflow-hidden transition-colors ${
                selected?.tmdb_id === r.tmdb_id && selected?.media_type === r.media_type
                  ? 'border-[var(--color-ocean-500)] bg-[var(--color-ocean-950)]/50'
                  : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
              }`}
            >
              {r.poster_path ? (
                <img
                  src={`${TMDB_IMAGE_BASE}${r.poster_path}`}
                  alt={r.title ?? ''}
                  className="w-full aspect-[2/3] object-cover"
                />
              ) : (
                <div className="w-full aspect-[2/3] bg-zinc-700 flex items-center justify-center text-zinc-500 text-xs">
                  No image
                </div>
              )}
              <div className="p-2 space-y-0.5">
                <div className="text-xs font-medium text-zinc-200 line-clamp-2 leading-tight">
                  {r.title}
                </div>
                <div className="text-xs text-zinc-500">
                  {year(r.first_air_date)} · {r.media_type}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
