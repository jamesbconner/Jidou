import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect, vi } from 'vitest'
import { MediaDetailModal } from '@/components/MediaDetailModal'
import type { RecentShowItem, RecentEpisodeItem } from '@/types/api'

function renderModal(item: Parameters<typeof MediaDetailModal>[0]['item'], onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <MediaDetailModal item={item} onClose={onClose} />
    </MemoryRouter>,
  )
  return onClose
}

const show: RecentShowItem = {
  id: 1,
  tmdb_id: 100,
  title: 'Test Show',
  media_type: 'tv',
  content_type: 'anime',
  poster_path: null,
  backdrop_path: null,
  overview: 'A show about testing.',
  tagline: 'Trust, but verify.',
  vote_average: 8.4,
  genres: [{ id: 16, name: 'Animation' }],
  release_date: '2024-01-15',
  status: 'Ended',
  number_of_seasons: 1,
  number_of_episodes: 12,
  runtime: 24,
  created_at: '2024-06-01T00:00:00Z',
  adult: false,
}

const episode: RecentEpisodeItem = {
  id: 5,
  show_id: 1,
  season_number: 1,
  episode_number: 3,
  name: 'The Pilot',
  overview: 'First episode overview.',
  air_date: '2024-01-15',
  file_tracked_at: '2024-06-01T00:00:00Z',
  still_path: null,
  runtime: 24,
  show: {
    id: 1,
    title: 'Test Show',
    content_type: 'anime',
    media_type: 'tv',
    poster_path: null,
    vote_average: 8.4,
    genres: [{ id: 16, name: 'Animation' }],
    adult: false,
  },
}

describe('MediaDetailModal', () => {
  test('show variant renders title, synopsis, rating, and genres', () => {
    renderModal({ kind: 'show', show })
    expect(screen.getAllByText('Test Show').length).toBeGreaterThan(0)
    expect(screen.getByText('A show about testing.')).toBeInTheDocument()
    expect(screen.getByText('★ 8.4')).toBeInTheDocument()
    expect(screen.getByText('Animation')).toBeInTheDocument()
  })

  test('episode variant renders show name and SxxEyy', () => {
    renderModal({ kind: 'episode', episode })
    expect(screen.getByText('The Pilot')).toBeInTheDocument()
    expect(screen.getByText(/Test Show — S01E03/)).toBeInTheDocument()
    expect(screen.getByText('First episode overview.')).toBeInTheDocument()
  })

  test('Escape key triggers onClose', () => {
    const onClose = renderModal({ kind: 'show', show })
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('close button triggers onClose', () => {
    const onClose = renderModal({ kind: 'show', show })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('view show link points at the correct show id', () => {
    renderModal({ kind: 'episode', episode })
    expect(screen.getByText('View show →')).toHaveAttribute('href', '/shows/1')
  })
})
