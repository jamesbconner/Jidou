import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi } from 'vitest'
import { DiscoverDetailModal } from '@/components/DiscoverDetailModal'
import type { DiscoverResult } from '@/types/api'

function makeResult(overrides: Partial<DiscoverResult> = {}): DiscoverResult {
  return {
    id: 100,
    media_type: 'tv',
    name: 'Test Show',
    title: null,
    overview: 'A show about testing.',
    poster_path: '/poster.jpg',
    backdrop_path: null,
    vote_average: 8.4,
    vote_count: 100,
    release_date: null,
    first_air_date: '2024-01-15',
    original_language: 'en',
    genre_ids: [16],
    origin_country: ['US'],
    adult: false,
    seeded_from: [],
    ...overrides,
  }
}

function renderModal(result: DiscoverResult, inLibraryShowId: number | null = null, onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <DiscoverDetailModal result={result} inLibraryShowId={inLibraryShowId} onClose={onClose} />
    </MemoryRouter>,
  )
  return onClose
}

describe('DiscoverDetailModal', () => {
  test('renders title, media type, rating, date, and overview', () => {
    renderModal(makeResult())
    expect(screen.getAllByText('Test Show').length).toBeGreaterThan(0)
    expect(screen.getByText('tv')).toBeInTheDocument()
    expect(screen.getByText('★ 8.4')).toBeInTheDocument()
    expect(screen.getByText('2024-01-15')).toBeInTheDocument()
    expect(screen.getByText('A show about testing.')).toBeInTheDocument()
  })

  test('TMDB link points at the correct URL and opens in a new tab', () => {
    renderModal(makeResult({ id: 100, media_type: 'tv' }))
    const link = screen.getByText('View on TMDB →')
    expect(link).toHaveAttribute('href', 'https://www.themoviedb.org/tv/100')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })

  test('movie media type builds a movie TMDB URL', () => {
    renderModal(makeResult({ id: 200, media_type: 'movie' }))
    expect(screen.getByText('View on TMDB →')).toHaveAttribute(
      'href',
      'https://www.themoviedb.org/movie/200',
    )
  })

  test('omits "View show" link when not in the library', () => {
    renderModal(makeResult(), null)
    expect(screen.queryByText('View show →')).not.toBeInTheDocument()
  })

  test('shows "View show" link pointing at the local show id when in the library', () => {
    renderModal(makeResult(), 7)
    expect(screen.getByText('View show →')).toHaveAttribute('href', '/shows/7')
  })

  test('close button triggers onClose', () => {
    const onClose = renderModal(makeResult())
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
