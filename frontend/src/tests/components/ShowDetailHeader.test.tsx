import { render, screen } from '@testing-library/react'
import { describe, test, expect } from 'vitest'
import { createElement } from 'react'
import { ShowDetailHeader } from '@/components/ShowDetailHeader'
import type { ShowRead } from '@/types/api'
import type { BannerStyle } from '@/hooks/useBannerStyle'

function makeShow(overrides: Partial<ShowRead> = {}): ShowRead {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Test Show',
    media_type: 'tv',
    release_date: '2020-05-01',
    vote_average: 8.1,
    content_type: null,
    backdrop_path: '/bd.jpg',
    ...overrides,
  } as unknown as ShowRead
}

function renderHeader(style: BannerStyle, show: ShowRead) {
  return render(
    createElement(ShowDetailHeader, {
      show,
      style,
      posterSrc: '/api/images/w500/poster.jpg',
      tmdbUrl: 'https://www.themoviedb.org/tv/100',
      primaryActions: createElement('button', { key: 'p' }, 'PRIMARY'),
      secondaryInfo: createElement('p', { key: 's' }, 'SECONDARY'),
      maintenanceActions: createElement('button', { key: 'm' }, 'MAINT'),
    }),
  )
}

describe('ShowDetailHeader', () => {
  test.each(['hero', 'contained', 'full'] as const)(
    'style "%s" renders the w1280 backdrop and every action slot',
    (style) => {
      const { container } = renderHeader(style, makeShow())

      expect(container.querySelector('img[src="/api/images/w1280/bd.jpg"]')).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: 'Test Show' })).toBeInTheDocument()
      expect(screen.getByText('PRIMARY')).toBeInTheDocument()
      expect(screen.getByText('SECONDARY')).toBeInTheDocument()
      expect(screen.getByText('MAINT')).toBeInTheDocument()
    },
  )

  test('style "none" renders the plain header with no backdrop', () => {
    const { container } = renderHeader('none', makeShow())

    expect(container.querySelector('img[src*="/api/images/w1280/"]')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Test Show' })).toBeInTheDocument()
    expect(screen.getByText('PRIMARY')).toBeInTheDocument()
  })

  test('a show without a backdrop_path falls back to the plain header for any style', () => {
    const { container } = renderHeader('hero', makeShow({ backdrop_path: null }))

    expect(container.querySelector('img[src*="/api/images/w1280/"]')).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Test Show' })).toBeInTheDocument()
  })
})
