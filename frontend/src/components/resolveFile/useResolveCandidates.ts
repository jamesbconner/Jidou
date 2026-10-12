import { useTmdbSuggestions } from '@/hooks/useFiles'
import { useTmdbSearch, useTmdbDetails, useLocalShowSearch } from '@/hooks/useShows'
import { useDebounce } from '@/hooks/useDebounce'
import type { TmdbSuggestion, ShowSearchResult } from '@/types/api'

export type SearchMode = 'suggestions' | 'title' | 'tmdb_id'

/** One selectable match for the file: a TMDB result or a show already in the library. */
export interface Candidate {
  key: string
  source: 'tmdb' | 'local'
  tmdb?: TmdbSuggestion
  local?: ShowSearchResult
}

interface Args {
  mode: SearchMode
  fileId: number
  /** Live text of the title-search box (also drives the library search in title mode). */
  query: string
  /** Parsed numeric TMDB id, or null when the box is empty or not a number. */
  tmdbId: number | null
  tmdbMediaType: 'tv' | 'movie'
  /** The file's parsed show name, used as the library query in suggestions mode. */
  parsedName: string
}

interface Result {
  /** TMDB candidates for the active mode (empty while loading or on error). */
  candidates: Candidate[]
  isLoading: boolean
  /** Error of the active mode's query only; null for title mode, which surfaces none. */
  error: unknown
  /** Library candidates for the same query, shown above the TMDB results. */
  localCandidates: Candidate[]
  localLoading: boolean
}

/**
 * Resolves the candidate matches for ResolveFileModal, one query per search mode.
 *
 * Each mode's query keeps exactly the `enabled` condition it had inline in the
 * modal, so inactive modes make no request. The hook is called by the modal
 * itself (not a child) so the queries' lifetime and firing order are unchanged.
 */
export function useResolveCandidates({
  mode,
  fileId,
  query,
  tmdbId,
  tmdbMediaType,
  parsedName,
}: Args): Result {
  const debouncedQuery = useDebounce(query, 300)

  const {
    data: suggestions,
    isFetching: suggestionsLoading,
    error: suggestionsError,
  } = useTmdbSuggestions(mode === 'suggestions' ? fileId : null)

  const { data: searchResults, isFetching: searchLoading } = useTmdbSearch(
    mode === 'title' && query.length >= 2 ? debouncedQuery : '',
    'multi',
  )

  const {
    data: tmdbIdResult,
    isFetching: tmdbIdLoading,
    error: tmdbIdError,
  } = useTmdbDetails(mode === 'tmdb_id' ? tmdbId : null, tmdbMediaType)

  // Local library candidates: the parsed name in suggestions mode, the typed
  // query in refine mode. Gated on the live input (not just the debounced
  // value) so switching modes never replays a stale query.
  const localQuery =
    mode === 'title'
      ? query.trim().length >= 2
        ? debouncedQuery
        : ''
      : mode === 'suggestions'
        ? parsedName
        : ''
  const { data: localResults = [], isFetching: localLoading } = useLocalShowSearch(localQuery, 6)

  // Build TMDB suggestion shape from raw TMDB search results (which use TmdbResult shape)
  const searchAsSuggestions: TmdbSuggestion[] = (searchResults?.results ?? [])
    .filter((r) => r.media_type === 'tv' || r.media_type === 'movie')
    .slice(0, 6)
    .map((r) => ({
      tmdb_id: r.id,
      title: r.name ?? r.title ?? null,
      media_type: r.media_type ?? null,
      overview: r.overview,
      poster_path: r.poster_path,
      first_air_date: r.first_air_date ?? r.release_date ?? null,
      vote_average: r.vote_average,
    }))

  const tmdbIdAsSuggestions: TmdbSuggestion[] = tmdbIdResult
    ? [
        {
          tmdb_id: tmdbIdResult.id,
          title: tmdbIdResult.name ?? tmdbIdResult.title ?? null,
          media_type: tmdbMediaType,
          overview: tmdbIdResult.overview,
          poster_path: tmdbIdResult.poster_path,
          first_air_date: tmdbIdResult.first_air_date ?? tmdbIdResult.release_date ?? null,
          vote_average: tmdbIdResult.vote_average,
        },
      ]
    : []

  const displayResults =
    mode === 'title'
      ? searchAsSuggestions
      : mode === 'tmdb_id'
        ? tmdbIdAsSuggestions
        : (suggestions?.results ?? [])

  return {
    candidates: displayResults.map((tmdb) => ({
      key: `${tmdb.tmdb_id}-${tmdb.media_type}`,
      source: 'tmdb',
      tmdb,
    })),
    isLoading:
      mode === 'title' ? searchLoading : mode === 'tmdb_id' ? tmdbIdLoading : suggestionsLoading,
    error: mode === 'suggestions' ? suggestionsError : mode === 'tmdb_id' ? tmdbIdError : null,
    localCandidates: localResults.map((local) => ({
      key: String(local.id),
      source: 'local',
      local,
    })),
    localLoading,
  }
}
