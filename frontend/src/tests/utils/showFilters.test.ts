import { describe, test, expect } from 'vitest'
import {
  sortShows,
  applyFilters,
  applyMissingFilters,
  deriveFilterOptions,
} from '@/utils/showFilters'
import type { ShowSortOrder } from '@/hooks/useShows'
import type { ShowList } from '@/types/api'

function makeShow(overrides: Partial<ShowList> = {}): ShowList {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Show Alpha',
    media_type: 'tv',
    poster_path: null,
    vote_average: null,
    release_date: null,
    original_language: null,
    content_type: 'tv',
    local_path: '/media/tv/show-alpha',
    episode_count: 10,
    watched_episode_count: 0,
    matched_file_count: 10,
    missing_episode_count: 0,
    missing_full_season_count: 0,
    aired_episode_count: 10,
    matched_episode_count: 10,
    aired_season_count: 1,
    matched_full_season_count: 1,
    has_active_rss_subscription: false,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as ShowList
}

const ids = (shows: ShowList[]) => shows.map((s) => s.id)

describe('sortShows', () => {
  const a = makeShow({
    id: 1, title: 'Alpha', created_at: '2026-01-01T00:00:00Z', release_date: '2020-05-01',
    last_air_date: '2024-01-01', vote_average: 7, number_of_episodes: 12,
    latest_episode_added_at: '2026-03-01T00:00:00Z',
  })
  const b = makeShow({
    id: 2, title: 'Bravo', created_at: '2026-02-01T00:00:00Z', release_date: '2022-05-01',
    last_air_date: '2025-01-01', vote_average: 9, number_of_episodes: 24,
    latest_episode_added_at: '2026-04-01T00:00:00Z',
  })
  const c = makeShow({
    id: 3, title: 'Charlie', created_at: '2026-03-01T00:00:00Z', release_date: null,
    last_air_date: null, vote_average: null, number_of_episodes: null,
    latest_episode_added_at: null,
  })
  // Deliberately unordered input.
  const input = [b, c, a]

  const cases: [ShowSortOrder, number[]][] = [
    ['title_asc', [1, 2, 3]],
    ['title_desc', [3, 2, 1]],
    ['added_desc', [3, 2, 1]],
    ['added_asc', [1, 2, 3]],
    ['release_desc', [2, 1, 3]],
    ['release_asc', [1, 2, 3]],
    ['last_aired_desc', [2, 1, 3]],
    ['rating_desc', [2, 1, 3]],
    ['episodes_desc', [2, 1, 3]],
    ['episodes_added_desc', [2, 1, 3]],
  ]

  test.each(cases)('orders by %s', (sort, expected) => {
    expect(ids(sortShows(input, sort))).toEqual(expected)
  })

  test('does not mutate the input array', () => {
    const copy = [...input]
    sortShows(input, 'title_asc')
    expect(input).toEqual(copy)
  })

  test('returns an empty array for empty input', () => {
    expect(sortShows([], 'title_asc')).toEqual([])
  })

  test('keeps incoming order for ties, including all-null keys', () => {
    const x = makeShow({ id: 10, title: 'Same', vote_average: null })
    const y = makeShow({ id: 11, title: 'Same', vote_average: null })
    const z = makeShow({ id: 12, title: 'Same', vote_average: null })
    expect(ids(sortShows([z, x, y], 'rating_desc'))).toEqual([12, 10, 11])
    expect(ids(sortShows([z, x, y], 'title_asc'))).toEqual([12, 10, 11])
  })

  test('keeps incoming order among equal non-null keys', () => {
    const x = makeShow({ id: 10, vote_average: 8 })
    const y = makeShow({ id: 11, vote_average: 8 })
    expect(ids(sortShows([y, x], 'rating_desc'))).toEqual([11, 10])
  })
})

describe('applyFilters', () => {
  const shows = [
    makeShow({
      id: 1, content_type: 'anime', status: 'Ended', genres: [{ id: 1, name: 'Drama' }],
      original_language: 'ja', vote_average: 8.5, next_episode_to_air: null,
    }),
    makeShow({
      id: 2, content_type: 'tv', status: 'Returning Series', genres: [{ id: 2, name: 'Comedy' }],
      original_language: 'en', vote_average: 6.5, next_episode_to_air: { air_date: '2030-01-01' },
    }),
    makeShow({ id: 3, content_type: null, status: null, genres: null, original_language: null, vote_average: null }),
  ] as ShowList[]

  const run = (
    over: Partial<{
      contentType: string; status: string; genre: string; language: string; upcoming: boolean; minRating: string
    }> = {},
  ) => {
    const o = { contentType: '', status: '', genre: '', language: '', upcoming: false, minRating: '', ...over }
    return ids(applyFilters(shows, o.contentType, o.status, o.genre, o.language, o.upcoming, o.minRating))
  }

  test('no criteria keeps every show', () => expect(run()).toEqual([1, 2, 3]))
  test('filters by content type', () => expect(run({ contentType: 'anime' })).toEqual([1]))
  test('"__unset__" keeps only shows without a content type', () =>
    expect(run({ contentType: '__unset__' })).toEqual([3]))
  test('filters by status', () => expect(run({ status: 'Ended' })).toEqual([1]))
  test('filters by genre', () => expect(run({ genre: 'Comedy' })).toEqual([2]))
  test('filters by language', () => expect(run({ language: 'en' })).toEqual([2]))
  test('upcoming keeps shows with a next episode', () => expect(run({ upcoming: true })).toEqual([2]))
  test('min rating excludes null and lower ratings', () => {
    expect(run({ minRating: '7' })).toEqual([1])
    expect(run({ minRating: '6' })).toEqual([1, 2])
  })
  test('combines criteria with AND', () =>
    expect(run({ contentType: 'tv', language: 'ja' })).toEqual([]))
  test('empty input yields empty output', () =>
    expect(applyFilters([], '', '', '', '', false, '')).toEqual([]))
})

describe('applyMissingFilters', () => {
  const shows = [
    makeShow({
      id: 1, content_type: 'anime', status: 'Ended', genres: [{ id: 1, name: 'Drama' }],
      original_language: 'ja', missing_episode_count: 1, missing_full_season_count: 0, matched_file_count: 1,
    }),
    makeShow({
      id: 2, content_type: 'tv', status: 'Returning Series', genres: [{ id: 2, name: 'Comedy' }],
      original_language: 'en', missing_episode_count: 6, missing_full_season_count: 1, matched_file_count: 3,
    }),
    makeShow({ id: 3, content_type: null, missing_episode_count: 12, missing_full_season_count: 2, matched_file_count: 9 }),
  ] as ShowList[]
  const watchlist = new Map<number, number>([[2, 99]])

  const run = (
    over: Partial<{
      contentType: string; status: string; genre: string; language: string
      minMissing: string; fullSeasonMissing: string; maxOwned: string; watchlistOnly: boolean
    }> = {},
  ) => {
    const o = {
      contentType: '', status: '', genre: '', language: '',
      minMissing: '', fullSeasonMissing: '', maxOwned: '', watchlistOnly: false, ...over,
    }
    return ids(
      applyMissingFilters(
        shows, o.contentType, o.status, o.genre, o.language,
        o.minMissing, o.fullSeasonMissing, o.maxOwned, o.watchlistOnly, watchlist,
      ),
    )
  }

  test('no criteria keeps every show', () => expect(run()).toEqual([1, 2, 3]))
  test('filters by content type, including unset', () => {
    expect(run({ contentType: 'tv' })).toEqual([2])
    expect(run({ contentType: '__unset__' })).toEqual([3])
  })
  test('filters by status, genre and language', () => {
    expect(run({ status: 'Ended' })).toEqual([1])
    expect(run({ genre: 'Comedy' })).toEqual([2])
    expect(run({ language: 'ja' })).toEqual([1])
  })
  test('"eq1" means exactly one missing episode', () =>
    expect(run({ minMissing: 'eq1' })).toEqual([1]))
  test('numeric min missing is a lower bound', () => {
    expect(run({ minMissing: '5' })).toEqual([2, 3])
    expect(run({ minMissing: '10' })).toEqual([3])
  })
  test('full-season-missing is a lower bound', () =>
    expect(run({ fullSeasonMissing: '2' })).toEqual([3]))
  test('max owned is an upper bound on matched files', () =>
    expect(run({ maxOwned: '3' })).toEqual([1, 2]))
  test('watchlist-only keeps shows present in the map', () =>
    expect(run({ watchlistOnly: true })).toEqual([2]))
  test('watchlist-only with an empty map keeps nothing', () =>
    expect(
      applyMissingFilters(shows, '', '', '', '', '', '', '', true, new Map()),
    ).toEqual([]))
  test('empty input yields empty output', () =>
    expect(applyMissingFilters([], '', '', '', '', '', '', '', false, watchlist)).toEqual([]))
})

describe('deriveFilterOptions', () => {
  test('returns distinct sorted values and skips empties', () => {
    const shows = [
      makeShow({ genres: [{ id: 1, name: 'Drama' }, { id: 2, name: 'Action' }], original_language: 'ja', status: 'Ended' }),
      makeShow({ genres: [{ id: 1, name: 'Drama' }], original_language: 'en', status: 'Ended' }),
      makeShow({ genres: null, original_language: null, status: null }),
    ] as ShowList[]
    expect(deriveFilterOptions(shows)).toEqual({
      genres: ['Action', 'Drama'],
      languages: ['en', 'ja'],
      statuses: ['Ended'],
    })
  })

  test('empty input gives empty option lists', () => {
    expect(deriveFilterOptions([])).toEqual({ genres: [], languages: [], statuses: [] })
  })
})
