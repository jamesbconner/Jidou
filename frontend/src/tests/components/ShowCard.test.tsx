import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect } from 'vitest'
import { ShowCard } from '@/components/ShowCard'
import type { ShowList } from '@/types/api'

function makeShow(overrides: Partial<ShowList> = {}): ShowList {
  return {
    id: 1,
    tmdb_id: 1396,
    title: 'Breaking Bad',
    media_type: 'tv',
    poster_path: null,
    vote_average: null,
    release_date: null,
    original_language: null,
    episode_count: 0,
    matched_file_count: 0,
    has_active_rss_subscription: false,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as ShowList
}

function renderCard(show: ShowList) {
  return render(
    <MemoryRouter>
      <ShowCard show={show} />
    </MemoryRouter>,
  )
}

describe('ShowCard', () => {
  test('shows the RSS badge when has_active_rss_subscription is true', () => {
    renderCard(makeShow({ has_active_rss_subscription: true }))
    expect(screen.getByTitle('Has an active RSS subscription')).toBeInTheDocument()
  })

  test('omits the RSS badge when has_active_rss_subscription is false', () => {
    renderCard(makeShow({ has_active_rss_subscription: false }))
    expect(screen.queryByTitle('Has an active RSS subscription')).not.toBeInTheDocument()
  })
})
