import { describe, test, expect } from 'vitest'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import type { TmdbResult } from '@/types/api'

function makeTvResult(overrides: Partial<TmdbResult> = {}): TmdbResult {
  return {
    id: 1396,
    name: 'Breaking Bad',
    overview: 'A chemistry teacher turns to crime.',
    poster_path: '/poster.jpg',
    backdrop_path: '/backdrop.jpg',
    vote_average: 8.9,
    vote_count: 12000,
    first_air_date: '2008-01-20',
    media_type: 'tv',
    original_language: 'en',
    genre_ids: [18, 80],
    origin_country: ['US'],
    adult: false,
    ...overrides,
  }
}

describe('buildShowCreatePayload', () => {
  test('maps every field from a tv result', () => {
    const result = makeTvResult()
    expect(buildShowCreatePayload(result)).toEqual({
      tmdb_id: 1396,
      title: 'Breaking Bad',
      media_type: 'tv',
      overview: 'A chemistry teacher turns to crime.',
      poster_path: '/poster.jpg',
      backdrop_path: '/backdrop.jpg',
      vote_average: 8.9,
      vote_count: 12000,
      release_date: '2008-01-20',
      original_language: 'en',
      genre_ids: [18, 80],
      origin_country: ['US'],
      adult: false,
    })
  })

  test('maps a movie result, preferring release_date over first_air_date', () => {
    const result = makeTvResult({
      id: 597,
      name: undefined,
      title: 'Titanic',
      media_type: 'movie',
      first_air_date: undefined,
      release_date: '1997-12-19',
    })
    const payload = buildShowCreatePayload(result)
    expect(payload.title).toBe('Titanic')
    expect(payload.media_type).toBe('movie')
    expect(payload.release_date).toBe('1997-12-19')
  })

  test('falls back to title when name is absent', () => {
    const result = makeTvResult({ name: undefined, title: 'Only Title' })
    expect(buildShowCreatePayload(result).title).toBe('Only Title')
  })

  test('falls back to "Unknown" when neither name nor title is present', () => {
    const result = makeTvResult({ name: undefined, title: undefined })
    expect(buildShowCreatePayload(result).title).toBe('Unknown')
  })

  test('defaults media_type to "tv" when absent', () => {
    const result = makeTvResult({ media_type: undefined })
    expect(buildShowCreatePayload(result).media_type).toBe('tv')
  })

  test('null-coalesces genre_ids, origin_country, and adult when absent', () => {
    const result = makeTvResult({ genre_ids: undefined, origin_country: undefined, adult: undefined })
    const payload = buildShowCreatePayload(result)
    expect(payload.genre_ids).toBeNull()
    expect(payload.origin_country).toBeNull()
    expect(payload.adult).toBeNull()
  })
})
