import { describe, test, expect } from 'vitest'
import {
  DEFAULT_MISSING_FILTERS,
  DEFAULT_SHOWS_FILTERS,
  countActiveMissingFilters,
  countActiveShowsFilters,
} from '@/utils/showFilters'
import { DEFAULT_RSS_FILTERS, filterSubscriptions } from '@/pages/rss/rssFilters'
import { episodeStats } from '@/pages/showDetail/episodeStats'
import { groupBySeason } from '@/pages/showDetail/EpisodesCard'
import { parseTmdbId } from '@/components/resolveFile/ResolveSections'
import type { EpisodeList, RssSubscriptionRead } from '@/types/api'

describe('countActiveShowsFilters / countActiveMissingFilters', () => {
  test('defaults count zero', () => {
    expect(countActiveShowsFilters(DEFAULT_SHOWS_FILTERS)).toBe(0)
    expect(countActiveMissingFilters(DEFAULT_MISSING_FILTERS)).toBe(0)
  })

  test('each criterion counts once, booleans included, sort does not count', () => {
    expect(
      countActiveShowsFilters({
        sort: 'rating_desc',
        filterContentType: 'tv',
        filterStatus: 'Ended',
        filterGenre: 'Drama',
        filterLanguage: 'en',
        filterUpcoming: true,
        filterMinRating: '5',
      }),
    ).toBe(6)
    expect(
      countActiveMissingFilters({
        filterContentType: 'tv',
        filterStatus: 's',
        filterGenre: 'g',
        filterLanguage: 'en',
        filterMinMissing: '1',
        filterFullSeasonMissing: '1',
        filterMaxOwned: '1',
        filterWatchlistOnly: true,
      }),
    ).toBe(8)
  })
})

describe('filterSubscriptions', () => {
  const sub = (id: number, over: Partial<RssSubscriptionRead>) =>
    ({ id, name: `Sub ${id}`, remote_key: 'k', feed_id: null, active: true, enabled_in_config: true, ...over }) as RssSubscriptionRead
  const subs = [
    sub(1, { name: 'Alpha', feed_id: 10 }),
    sub(2, { remote_key: null, active: false, enabled_in_config: false }),
    sub(3, { feed_id: 11 }),
  ]

  test('default filters keep everything in order', () => {
    expect(filterSubscriptions(subs, DEFAULT_RSS_FILTERS).map((s) => s.id)).toEqual([1, 2, 3])
  })

  test.each([
    [{ nameSearch: 'ALPH' }, [1]],
    [{ enabledFilter: 'disabled' as const }, [2]],
    [{ activeFilter: 'active' as const }, [1, 3]],
    [{ keyFilter: 'stub' as const }, [2]],
    [{ feedFilter: 'unlinked' as const }, [2]],
    [{ feedFilter: 11 }, [3]],
    [{ enabledFilter: 'enabled' as const, keyFilter: 'keyed' as const, feedFilter: 10 }, [1]],
  ])('%o', (patch, ids) => {
    expect(filterSubscriptions(subs, { ...DEFAULT_RSS_FILTERS, ...patch }).map((s) => s.id)).toEqual(ids)
  })
})

describe('episodeStats / groupBySeason', () => {
  const ep = (id: number, season: number, over: Partial<EpisodeList> = {}) =>
    ({ id, season_number: season, episode_number: id, file_tracked: false, watched: false, air_date: '2000-01-01', ...over }) as EpisodeList

  test('counts tracked, watched and missing; all-watched needs at least one episode', () => {
    const eps = [ep(1, 1, { file_tracked: true, watched: true }), ep(2, 1, { watched: true })]
    const stats = episodeStats(eps, true, '2026-01-01')
    expect(stats).toMatchObject({ trackedCount: 1, watchedCount: 2, allWatched: true })
    expect(stats.missingCount).toBeGreaterThanOrEqual(0)
    expect(episodeStats([], true, '2026-01-01').allWatched).toBe(false)
  })

  test('missing count is zero when the show does not track missing episodes', () => {
    expect(episodeStats([ep(1, 1)], false, '2026-01-01').missingCount).toBe(0)
  })

  test('groups by season preserving order', () => {
    const grouped = groupBySeason([ep(1, 2), ep(2, 1), ep(3, 2)])
    expect(Object.keys(grouped).sort()).toEqual(['1', '2'])
    expect(grouped[2].map((e) => e.id)).toEqual([1, 3])
  })
})

describe('parseTmdbId', () => {
  test.each([
    ['1668', 1668],
    ['  42 ', 42],
    ['', null],
    ['12a', null],
    ['-5', null],
    ['1.5', null],
  ])('%j', (input, expected) => {
    expect(parseTmdbId(input)).toBe(expected)
  })
})
