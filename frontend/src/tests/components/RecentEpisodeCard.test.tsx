import { render, screen } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { RecentEpisodeCard } from '@/components/RecentEpisodeCard'
import type { RecentEpisodeItem } from '@/types/api'

function makeEpisode(overrides: Partial<RecentEpisodeItem> = {}): RecentEpisodeItem {
  return {
    id: 1,
    show_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Pilot',
    air_date: '2026-01-01',
    file_tracked_at: '2026-01-02T00:00:00Z',
    still_path: '/still.jpg',
    show: {
      id: 1,
      title: 'Breaking Bad',
      media_type: 'tv',
      content_type: 'tv',
      poster_path: '/poster.jpg',
      vote_average: null,
    },
    ...overrides,
  } as RecentEpisodeItem
}

function renderCard(episode: RecentEpisodeItem, preferPosters: boolean) {
  return render(
    <RecentEpisodeCard episode={episode} sort="tracked" preferPosters={preferPosters} onClick={vi.fn()} />,
  )
}

describe('RecentEpisodeCard', () => {
  test('uses the episode still when preferPosters is off and a still exists', () => {
    renderCard(makeEpisode(), false)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/images/w300/still.jpg')
  })

  test('falls back to the show poster when preferPosters is off and no still exists', () => {
    renderCard(makeEpisode({ still_path: null }), false)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/images/w300/poster.jpg')
  })

  test('uses the show poster when preferPosters is on, even though a still exists', () => {
    renderCard(makeEpisode(), true)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/images/w300/poster.jpg')
  })

  test('falls back to the still when preferPosters is on but the show has no poster', () => {
    renderCard(makeEpisode({ show: { ...makeEpisode().show, poster_path: null } }), true)
    expect(screen.getByRole('img')).toHaveAttribute('src', '/api/images/w300/still.jpg')
  })
})
