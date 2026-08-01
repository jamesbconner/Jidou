import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect } from 'vitest'
import { MissingEpisodesList } from '@/components/MissingEpisodesList'
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

describe('MissingEpisodesList', () => {
  test('shows an up-to-date message when nothing is missing', () => {
    render(<MissingEpisodesList episodes={[makeEpisode({ file_tracked: true })]} />)
    expect(screen.getByText(/up to date/i)).toBeInTheDocument()
  })

  test('summarizes missing count and season count', () => {
    const episodes = [
      makeEpisode({ id: 1, season_number: 1, episode_number: 1, file_tracked: false }),
      makeEpisode({ id: 2, season_number: 2, episode_number: 1, file_tracked: false }),
    ]
    render(<MissingEpisodesList episodes={episodes} />)
    expect(screen.getByText(/2 missing episodes across 2 seasons/i)).toBeInTheDocument()
  })

  test('lists a season row per season with a gap', () => {
    const episodes = [
      makeEpisode({ id: 1, season_number: 1, episode_number: 1, file_tracked: false }),
      makeEpisode({ id: 2, season_number: 1, episode_number: 2, file_tracked: true }),
    ]
    render(<MissingEpisodesList episodes={episodes} />)
    expect(screen.getByText('Season 1')).toBeInTheDocument()
  })

  test('expands a season row on click to reveal episode detail', () => {
    const episodes = [
      makeEpisode({
        id: 1,
        season_number: 1,
        episode_number: 3,
        name: 'The Missing One',
        file_tracked: false,
      }),
    ]
    render(<MissingEpisodesList episodes={episodes} />)
    expect(screen.queryByText('The Missing One')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Season 1'))
    expect(screen.getByText('The Missing One')).toBeInTheDocument()
    expect(screen.getByText(/S01E03/)).toBeInTheDocument()
  })
})
