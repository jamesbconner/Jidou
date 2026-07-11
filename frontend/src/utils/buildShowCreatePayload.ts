import type { TmdbResult, ShowCreate } from '@/types/api'

/**
 * Build a ShowCreate payload from a raw TMDB search result.
 */
export function buildShowCreatePayload(result: TmdbResult): ShowCreate {
  return {
    tmdb_id: result.id,
    title: result.name ?? result.title ?? 'Unknown',
    media_type: result.media_type ?? 'tv',
    overview: result.overview,
    poster_path: result.poster_path,
    backdrop_path: result.backdrop_path,
    vote_average: result.vote_average,
    vote_count: result.vote_count,
    release_date: result.first_air_date ?? result.release_date,
    original_language: result.original_language,
    genre_ids: result.genre_ids ?? null,
    origin_country: result.origin_country ?? null,
    adult: result.adult ?? null,
  }
}
