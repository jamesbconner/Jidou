import { describe, test, expect } from 'vitest'
import { computeMissingEpisodes } from '@/utils/missingEpisodes'
import type { EpisodeList } from '@/types/api'

function makeEpisode(overrides: Partial<EpisodeList> = {}): EpisodeList {
  return {
    id: 1,
    show_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Pilot',
    overview: null,
    air_date: '2020-01-01',
    episode_type: null,
    absolute_episode_number: null,
    file_tracked: false,
    tracked_filename: null,
    tracked_source: null,
    watched: false,
    watched_at: null,
    file_tracked_at: null,
    backing_files: [],
    tracked_filename_display: null,
    ...overrides,
  } as EpisodeList
}

const TODAY = '2026-01-01'

describe('computeMissingEpisodes', () => {
  test('groups aired, untracked episodes by season', () => {
    const episodes = [
      makeEpisode({ id: 1, season_number: 1, episode_number: 1, file_tracked: false }),
      makeEpisode({ id: 2, season_number: 1, episode_number: 2, file_tracked: true }),
      makeEpisode({ id: 3, season_number: 2, episode_number: 1, file_tracked: false }),
    ]
    const result = computeMissingEpisodes(episodes, TODAY)
    expect(result).toEqual([
      { seasonNumber: 1, aired: 2, missing: [episodes[0]] },
      { seasonNumber: 2, aired: 1, missing: [episodes[2]] },
    ])
  })

  test('excludes episodes that have not aired yet', () => {
    const episodes = [makeEpisode({ air_date: '2026-06-01', file_tracked: false })]
    expect(computeMissingEpisodes(episodes, TODAY)).toEqual([])
  })

  test('excludes episodes with no air date', () => {
    const episodes = [makeEpisode({ air_date: null, file_tracked: false })]
    expect(computeMissingEpisodes(episodes, TODAY)).toEqual([])
  })

  test('excludes tracked episodes', () => {
    const episodes = [makeEpisode({ file_tracked: true })]
    expect(computeMissingEpisodes(episodes, TODAY)).toEqual([])
  })

  test('sorts seasons and episodes numerically', () => {
    const episodes = [
      makeEpisode({ id: 1, season_number: 10, episode_number: 2, file_tracked: false }),
      makeEpisode({ id: 2, season_number: 2, episode_number: 10, file_tracked: false }),
      makeEpisode({ id: 3, season_number: 2, episode_number: 2, file_tracked: false }),
    ]
    const result = computeMissingEpisodes(episodes, TODAY)
    expect(result.map((s) => s.seasonNumber)).toEqual([2, 10])
    expect(result[0].missing.map((e) => e.episode_number)).toEqual([2, 10])
  })

  test('returns an empty array when nothing is missing', () => {
    expect(computeMissingEpisodes([], TODAY)).toEqual([])
  })
})
