import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ShowPreviewModal } from '@/components/ShowPreviewModal'
import type { ShowRead, WatchlistRead } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(MemoryRouter, {}, children),
    )
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735); plain assignment avoids it.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

function baseShow(overrides: Partial<ShowRead> = {}): ShowRead {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Test Show',
    media_type: 'tv',
    overview: 'A show about testing.',
    poster_path: '/poster.jpg',
    backdrop_path: null,
    vote_average: 8.4,
    vote_count: 0,
    release_date: '2024-01-15',
    original_language: null,
    cached: false,
    content_type: null,
    sys_name: null,
    aliases: null,
    aliases_sources: null,
    genres: null,
    origin_country: null,
    last_air_date: null,
    last_episode_to_air: null,
    next_episode_to_air: null,
    homepage: null,
    external_ids: null,
    episode_groups: null,
    episode_group_map: null,
    status: null,
    in_production: null,
    number_of_seasons: null,
    number_of_episodes: null,
    networks: null,
    show_type: null,
    runtime: null,
    tagline: null,
    local_path: null,
    adult: null,
    list_poster_path: null,
    detail_poster_path: null,
    track_missing_episodes: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function baseEntry(overrides: Partial<WatchlistRead> = {}): WatchlistRead {
  return {
    id: 1,
    show_id: 1,
    show: { title: 'Test Show', tmdb_id: 100, poster_path: '/poster.jpg', backdrop_path: null },
    status: 'watching',
    notes: null,
    position: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    next_up: null,
    ...overrides,
  }
}

function renderModal(entry: WatchlistRead, show: ShowRead, onClose = vi.fn()) {
  vi.mocked(fetch).mockResolvedValue(mockResponse(show))
  render(<ShowPreviewModal entry={entry} onClose={onClose} />, { wrapper: makeWrapper() })
  return onClose
}

describe('ShowPreviewModal', () => {
  test('renders title, status badge, and fetched show metadata', async () => {
    renderModal(baseEntry(), baseShow())
    expect(screen.getByRole('heading', { name: 'Test Show' })).toBeInTheDocument()
    expect(screen.getByText('Watching')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('A show about testing.')).toBeInTheDocument())
    expect(screen.getByText((_, el) => el?.textContent === '2024 · tv · ★ 8.4 · TMDB #100'))
      .toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'TMDB #100' })).toHaveAttribute(
      'href',
      'https://www.themoviedb.org/tv/100',
    )
  })

  test('renders the next-up episode when present', async () => {
    renderModal(
      baseEntry({
        next_up: {
          season_number: 2,
          episode_number: 6,
          name: 'The Long Way Home',
          air_date: '2026-01-15',
          file_tracked: true,
        },
      }),
      baseShow(),
    )
    expect(
      screen.getByText((_, el) => el?.textContent === 'S02E06 — The Long Way Home ✓'),
    ).toBeInTheDocument()
    expect(screen.getByText('Airs 2026-01-15')).toBeInTheDocument()
  })

  test('shows a placeholder when there is no unwatched episode', async () => {
    renderModal(baseEntry({ next_up: null }), baseShow())
    expect(screen.getByText('No unwatched episodes.')).toBeInTheDocument()
  })

  test('close button triggers onClose', async () => {
    const onClose = renderModal(baseEntry(), baseShow())
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('View Full Show Page links to the show detail route', async () => {
    renderModal(baseEntry({ show_id: 7 }), baseShow({ id: 7 }))
    expect(screen.getByText('View Full Show Page')).toHaveAttribute('href', '/shows/7')
  })
})
