import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Shows from '@/pages/Shows'
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

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      MemoryRouter,
      {},
      createElement(QueryClientProvider, { client: qc }, children),
    )
}

// See Watchlist.test.tsx for why a plain assignment (not vi.spyOn) is used here.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
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

function mockShowsPage(
  shows: ShowList[],
  watchlistShowIds: number[] = [],
  tmdbResults: unknown[] = [],
) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input)
    if (url.startsWith('/api/shows/search?')) {
      return mockResponse({ results: tmdbResults, total_results: tmdbResults.length, total_pages: 1, page: 1 })
    }
    if (url.startsWith('/api/shows?')) return mockResponse(shows)
    if (url.startsWith('/api/watchlist?')) {
      return mockResponse(
        watchlistShowIds.map((show_id, i) => ({ id: i + 1, show_id, position: i + 1 })),
      )
    }
    return mockResponse([])
  })
}

async function openMissingEpisodesTab() {
  render(<Shows />, { wrapper: makeWrapper() })
  const tab = await screen.findByRole('button', { name: /Missing Episodes/ })
  fireEvent.click(tab)
}

describe('Shows page — Missing Episodes tab', () => {
  test('shows an empty state when no shows have missing episodes', async () => {
    mockShowsPage([makeShow({ missing_episode_count: 0 })])
    await openMissingEpisodesTab()
    await waitFor(() =>
      expect(screen.getByText('No missing episodes across 1 show.')).toBeInTheDocument(),
    )
  })

  test('lists shows with missing episodes, sorted by count descending', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Low Gaps', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'High Gaps', missing_episode_count: 40 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('High Gaps')).toBeInTheDocument())
    const rows = screen.getAllByRole('row').filter((r) => r.querySelector('td'))
    expect(rows[0]).toHaveTextContent('High Gaps')
    expect(rows[1]).toHaveTextContent('Low Gaps')
  })

  test('omits shows with zero missing episodes from the list', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Complete Show', missing_episode_count: 0 }),
      makeShow({ id: 2, title: 'Gappy Show', missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Gappy Show')).toBeInTheDocument())
    expect(screen.queryByText('Complete Show')).not.toBeInTheDocument()
  })

  test('filters the list by title', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Breaking Bad', missing_episode_count: 3 }),
      makeShow({ id: 2, title: 'Better Call Saul', missing_episode_count: 5 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Breaking Bad')).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText('Filter by title…'), {
      target: { value: 'saul' },
    })
    expect(screen.queryByText('Breaking Bad')).not.toBeInTheDocument()
    expect(screen.getByText('Better Call Saul')).toBeInTheDocument()
  })

  test('show title links to show detail page', async () => {
    mockShowsPage([makeShow({ id: 42, title: 'Linked Show', missing_episode_count: 1 })])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Linked Show')).toBeInTheDocument())
    expect(screen.getByText('Linked Show').closest('a')).toHaveAttribute('href', '/shows/42')
  })

  test('filters the list by content type', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Anime Show', content_type: 'anime', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'TV Show', content_type: 'tv', missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Anime Show')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('All types'), { target: { value: 'anime' } })
    expect(screen.getByText('Anime Show')).toBeInTheDocument()
    expect(screen.queryByText('TV Show')).not.toBeInTheDocument()
  })

  test('filters the list by status', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Ended Show', status: 'Ended', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'Airing Show', status: 'Returning Series', missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Ended Show')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('All statuses'), { target: { value: 'Ended' } })
    expect(screen.getByText('Ended Show')).toBeInTheDocument()
    expect(screen.queryByText('Airing Show')).not.toBeInTheDocument()
  })

  test('filters the list by genre', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Drama Show', genres: [{ id: 1, name: 'Drama' }], missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'Comedy Show', genres: [{ id: 2, name: 'Comedy' }], missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Drama Show')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('All genres'), { target: { value: 'Comedy' } })
    expect(screen.getByText('Comedy Show')).toBeInTheDocument()
    expect(screen.queryByText('Drama Show')).not.toBeInTheDocument()
  })

  test('filters the list by language', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'English Show', original_language: 'en', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'Japanese Show', original_language: 'ja', missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('English Show')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('All languages'), { target: { value: 'ja' } })
    expect(screen.getByText('Japanese Show')).toBeInTheDocument()
    expect(screen.queryByText('English Show')).not.toBeInTheDocument()
  })

  test('filters the list by minimum missing count', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Few Missing', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'Many Missing', missing_episode_count: 12 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Few Missing')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('Any missing'), { target: { value: '10' } })
    expect(screen.getByText('Many Missing')).toBeInTheDocument()
    expect(screen.queryByText('Few Missing')).not.toBeInTheDocument()
  })

  test('filters the list to shows missing exactly 1 episode', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'One Missing', missing_episode_count: 1 }),
      makeShow({ id: 2, title: 'Two Missing', missing_episode_count: 2 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('One Missing')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('Any missing'), { target: { value: 'eq1' } })
    expect(screen.getByText('One Missing')).toBeInTheDocument()
    expect(screen.queryByText('Two Missing')).not.toBeInTheDocument()
  })

  test('shows total/matched episode and season counts alongside the missing counts', async () => {
    mockShowsPage([
      makeShow({
        id: 1,
        title: 'Partial Show',
        missing_episode_count: 3,
        missing_full_season_count: 0,
        aired_episode_count: 12,
        matched_episode_count: 9,
        aired_season_count: 2,
        matched_full_season_count: 1,
      }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Partial Show')).toBeInTheDocument())

    const row = screen.getByText('Partial Show').closest('tr')
    expect(row).not.toBeNull()
    expect(row!.textContent).toContain('12')
    expect(row!.textContent).toContain('9')
    expect(row!.textContent).toContain('2')
    expect(row!.textContent).toContain('1')
  })

  test('filters the list to shows missing a whole season', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Whole Season Gone', missing_episode_count: 12, missing_full_season_count: 1 }),
      makeShow({ id: 2, title: 'Scattered Gaps', missing_episode_count: 4, missing_full_season_count: 0 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Whole Season Gone')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('Any'), { target: { value: '1' } })
    expect(screen.getByText('Whole Season Gone')).toBeInTheDocument()
    expect(screen.queryByText('Scattered Gaps')).not.toBeInTheDocument()
  })

  test('filters the list by max episodes owned', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Barely Started', missing_episode_count: 8, matched_file_count: 1 }),
      makeShow({ id: 2, title: 'Well Stocked', missing_episode_count: 2, matched_file_count: 10 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Barely Started')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('Any owned'), { target: { value: '2' } })
    expect(screen.getByText('Barely Started')).toBeInTheDocument()
    expect(screen.queryByText('Well Stocked')).not.toBeInTheDocument()
  })

  test('Clear filters resets the new missing-episode filters', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'One Missing', missing_episode_count: 1, missing_full_season_count: 1, matched_file_count: 1 }),
      makeShow({ id: 2, title: 'Everything Else', missing_episode_count: 4, missing_full_season_count: 0, matched_file_count: 10 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('One Missing')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('Any missing'), { target: { value: 'eq1' } })
    fireEvent.change(screen.getByDisplayValue('Any'), { target: { value: '1' } })
    fireEvent.change(screen.getByDisplayValue('Any owned'), { target: { value: '1' } })
    expect(screen.getByText(/Clear filters \(3\)/)).toBeInTheDocument()
    expect(screen.queryByText('Everything Else')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Clear filters/ }))
    expect(screen.getByText('Everything Else')).toBeInTheDocument()
    expect(screen.getByText('One Missing')).toBeInTheDocument()
  })

  test('filters the list to watchlist-only shows', async () => {
    mockShowsPage(
      [
        makeShow({ id: 1, title: 'On Watchlist', missing_episode_count: 2 }),
        makeShow({ id: 2, title: 'Not On Watchlist', missing_episode_count: 3 }),
      ],
      [1],
    )
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('On Watchlist')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Watchlist only'))
    await waitFor(() => expect(screen.queryByText('Not On Watchlist')).not.toBeInTheDocument())
    expect(screen.getByText('On Watchlist')).toBeInTheDocument()
  })

  test('shows a loading state, not a false empty list, while the watchlist is still loading and Watchlist only is enabled', async () => {
    let resolveWatchlist: (value: Response) => void = () => {}
    const watchlistPromise = new Promise<Response>((resolve) => { resolveWatchlist = resolve })
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input)
      if (url.startsWith('/api/shows?')) {
        return mockResponse([makeShow({ id: 1, title: 'Gappy Show', missing_episode_count: 3 })])
      }
      if (url.startsWith('/api/watchlist?')) return watchlistPromise
      return mockResponse([])
    })

    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Gappy Show')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Watchlist only'))
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(screen.queryByText(/shows match the current filters/)).not.toBeInTheDocument()

    resolveWatchlist(mockResponse([{ id: 1, show_id: 1, position: 1 }]))
    await waitFor(() => expect(screen.getByText('Gappy Show')).toBeInTheDocument())
  })

  test('Clear filters resets missing-tab filters independently of the library tab', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Anime Show', content_type: 'anime', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'TV Show', content_type: 'tv', missing_episode_count: 3 }),
    ])
    await openMissingEpisodesTab()
    await waitFor(() => expect(screen.getByText('Anime Show')).toBeInTheDocument())

    fireEvent.change(screen.getByDisplayValue('All types'), { target: { value: 'anime' } })
    expect(screen.queryByText('TV Show')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Clear filters/ }))
    expect(screen.getByText('TV Show')).toBeInTheDocument()
    expect(screen.getByText('Anime Show')).toBeInTheDocument()
  })

  test('does not show the Missing Episodes table under the Data Quality tab', async () => {
    mockShowsPage([makeShow({ id: 1, title: 'Gappy Show', missing_episode_count: 3 })])
    render(<Shows />, { wrapper: makeWrapper() })
    const dqTab = await screen.findByRole('button', { name: /^Data Quality/ })
    fireEvent.click(dqTab)
    await waitFor(() =>
      expect(screen.getByText(/No data quality issues found/)).toBeInTheDocument(),
    )
    expect(screen.queryByText('Gappy Show')).not.toBeInTheDocument()
  })
})

describe('Shows page — Search Shows modal', () => {
  test('clicking a TMDB result poster opens its metadata detail modal', async () => {
    mockShowsPage([], [], [
      {
        id: 55,
        name: 'Distant Planet',
        overview: 'A show about a distant planet.',
        poster_path: '/distant.jpg',
        backdrop_path: null,
        vote_average: 7.8,
        vote_count: 200,
        first_air_date: '2023-05-01',
        media_type: 'tv',
        original_language: 'en',
      },
    ])
    render(<Shows />, { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Search shows…' }))
    fireEvent.click(screen.getByRole('button', { name: 'TMDB' }))
    fireEvent.change(screen.getByPlaceholderText('Search TMDB…'), { target: { value: 'distant' } })

    fireEvent.click(await screen.findByAltText('Distant Planet'))

    await waitFor(() => expect(screen.getAllByText('Distant Planet').length).toBeGreaterThan(1))
    expect(screen.getByText('A show about a distant planet.')).toBeInTheDocument()
    expect(screen.getByText('★ 7.8')).toBeInTheDocument()
  })
})
