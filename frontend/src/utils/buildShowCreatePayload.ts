import type { ShowCreate } from '@/types/api'

// Loosest common shape needed to build a ShowCreate — deliberately more
// permissive (fields nullable, not just optional) than TmdbResult so both
// TmdbResult and DiscoverResult (whose backend schema declares these fields
// as nullable) satisfy it without a translation layer between the two.
interface ShowCreatePayloadInput {
  id: number
  title?: string | null
  name?: string | null
  overview?: string | null
  poster_path?: string | null
  backdrop_path?: string | null
  vote_average?: number | null
  vote_count?: number | null
  release_date?: string | null
  first_air_date?: string | null
  media_type?: string | null
  original_language?: string | null
  genre_ids?: number[] | null
  origin_country?: string[] | null
  adult?: boolean | null
}

/**
 * Build a ShowCreate payload from a raw TMDB search result or discover item.
 */
export function buildShowCreatePayload(result: ShowCreatePayloadInput): ShowCreate {
  return {
    tmdb_id: result.id,
    title: result.name ?? result.title ?? 'Unknown',
    media_type: result.media_type ?? 'tv',
    overview: result.overview ?? null,
    poster_path: result.poster_path ?? null,
    backdrop_path: result.backdrop_path ?? null,
    vote_average: result.vote_average ?? null,
    vote_count: result.vote_count ?? 0,
    release_date: result.first_air_date ?? result.release_date ?? null,
    original_language: result.original_language ?? null,
    genre_ids: result.genre_ids ?? null,
    origin_country: result.origin_country ?? null,
    adult: result.adult ?? null,
  }
}
