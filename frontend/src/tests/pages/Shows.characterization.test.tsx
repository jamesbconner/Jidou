import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Shows from '@/pages/Shows'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of the Shows page shell: tab/filter DOM, the search-modal
 * states in both modes, the request sequence, and the state retained across tab
 * switches. Written before the presentational extraction; it must pass
 * unchanged afterwards.
 */

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, createElement(QueryClientProvider, { client: qc }, children))
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const makeShow = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  tmdb_id: 100,
  title: 'Show Alpha',
  media_type: 'tv',
  poster_path: null,
  vote_average: 7.1,
  release_date: '2020-01-01',
  original_language: 'en',
  content_type: 'tv',
  local_path: '/media/tv/show-alpha',
  episode_count: 10,
  watched_episode_count: 2,
  matched_file_count: 10,
  missing_episode_count: 0,
  missing_full_season_count: 0,
  aired_episode_count: 10,
  matched_episode_count: 10,
  aired_season_count: 1,
  matched_full_season_count: 1,
  has_active_rss_subscription: false,
  genres: ['Drama'],
  status: 'Ended',
  created_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

const shows = [
  makeShow(),
  makeShow({ id: 2, tmdb_id: 200, title: 'Show Beta', missing_episode_count: 4, content_type: 'anime', local_path: null }),
  makeShow({ id: 3, tmdb_id: 300, title: 'Show Gamma', media_type: 'movie', content_type: 'movie', poster_path: '/g.jpg' }),
]

interface Opts {
  local?: unknown[]
  tmdb?: unknown[]
}

function mockApi(opts: Opts = {}): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.startsWith('/api/shows/tmdb/search?'))
      return mockResponse({ results: opts.tmdb ?? [], total_results: 0, total_pages: 1, page: 1 })
    if (url.startsWith('/api/shows/search?')) return mockResponse(opts.local ?? [])
    if (url.startsWith('/api/shows?')) return mockResponse(shows)
    if (url.startsWith('/api/watchlist?')) return mockResponse([{ id: 5, show_id: 2, position: 1 }])
    return mockResponse([])
  })
  return log
}

const tmdbResult = (id: number, name: string, media_type = 'tv') => ({
  id,
  name,
  title: null,
  media_type,
  overview: 'Overview text.',
  poster_path: '/t.jpg',
  first_air_date: '2021-05-01',
  vote_average: 8,
})

async function renderPage() {
  render(<Shows />, { wrapper: makeWrapper() })
  await screen.findByText('Show Alpha')
}

async function openModal() {
  fireEvent.click(screen.getByRole('button', { name: 'Search shows…' }))
  return screen.findByPlaceholderText('Search your library…')
}

describe('Shows characterization: tabs and filters', () => {
  test('library tab DOM and mount request order', async () => {
    const log = mockApi()
    await renderPage()
    await sleep(20)
    expect(log).toMatchSnapshot('mount requests')
    expect(domSnapshot()).toMatchSnapshot('library dom')
  })

  test('data quality and missing tabs DOM; library state survives a tab round trip', async () => {
    mockApi()
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Data Quality/ }))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('data dom')
    fireEvent.click(screen.getByRole('button', { name: /Missing Episodes/ }))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('missing dom')
    fireEvent.change(screen.getByPlaceholderText('Filter by title…'), { target: { value: 'beta' } })
    fireEvent.click(screen.getByRole('button', { name: /Data Quality/ }))
    fireEvent.click(screen.getByRole('button', { name: /Missing Episodes/ }))
    expect((screen.getByPlaceholderText('Filter by title…') as HTMLInputElement).value).toBe('beta')
  })

  test('active filters show Clear filters per tab with counts, and clearing resets', async () => {
    window.localStorage.setItem(
      'jidou:shows-filters',
      JSON.stringify({
        sort: 'title_asc',
        filterContentType: 'anime',
        filterStatus: 'Ended',
        filterGenre: '',
        filterLanguage: 'en',
        filterUpcoming: true,
        filterMinRating: '5',
      }),
    )
    window.localStorage.setItem(
      'jidou:shows-missing-filters',
      JSON.stringify({
        filterContentType: 'tv',
        filterStatus: '',
        filterGenre: '',
        filterLanguage: '',
        filterMinMissing: '2',
        filterFullSeasonMissing: '',
        filterMaxOwned: '',
        filterWatchlistOnly: true,
      }),
    )
    const log = mockApi()
    render(<Shows />, { wrapper: makeWrapper() })
    await screen.findByRole('button', { name: 'Clear filters (5)' })
    expect(domSnapshot()).toMatchSnapshot('library filtered dom')
    fireEvent.click(screen.getByRole('button', { name: /Missing Episodes/ }))
    await screen.findByRole('button', { name: 'Clear filters (3)' })
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('missing filtered dom')
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters (3)' }))
    expect(screen.queryByRole('button', { name: /Clear filters/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Shows in Library/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters (5)' }))
    expect(screen.queryByRole('button', { name: /Clear filters/ })).toBeNull()
    expect(JSON.parse(window.localStorage.getItem('jidou:shows-filters') ?? '{}')).toMatchSnapshot('cleared stored filters')
    expect(log).toMatchSnapshot('requests')
  })
})

describe('Shows characterization: search modal', () => {
  test('library mode states: short, searching, results, empty', async () => {
    const log = mockApi({
      local: [
        { id: 2, tmdb_id: 200, title: 'Show Beta', media_type: 'tv', content_type: 'anime', local_path: '/m', release_date: '2020-02-02', poster_path: '/b.jpg', matched_on: 'alias' },
        { id: 3, tmdb_id: 300, title: 'Show Gamma', media_type: 'tv', content_type: null, local_path: null, release_date: null, poster_path: null, matched_on: 'path' },
        { id: 4, tmdb_id: 400, title: 'Show Delta', media_type: 'tv', content_type: null, local_path: null, release_date: null, poster_path: null, matched_on: 'sys_name' },
      ],
    })
    await renderPage()
    const input = await openModal()
    expect(domSnapshot()).toMatchSnapshot('library short')
    fireEvent.change(input, { target: { value: 'sho' } })
    expect(domSnapshot()).toMatchSnapshot('library debouncing')
    await screen.findByText('Show Beta', {}, { timeout: 2000 })
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('library results')
    expect(log.filter((l) => l.includes('/search'))).toMatchSnapshot('library search requests')
  })

  test('library mode with no hits', async () => {
    mockApi({ local: [] })
    await renderPage()
    const input = await openModal()
    fireEvent.change(input, { target: { value: 'zzzz' } })
    await screen.findByText(/No shows found for/, {}, { timeout: 2000 })
    expect(domSnapshot()).toMatchSnapshot('library empty')
  })

  test('tmdb mode: short, results (in-library + add), empty; query retained across modes', async () => {
    const log = mockApi({
      tmdb: [tmdbResult(200, 'Show Beta'), tmdbResult(900, 'Brand New'), tmdbResult(300, 'Show Gamma', 'movie')],
    })
    await renderPage()
    const input = await openModal()
    fireEvent.click(screen.getByRole('button', { name: 'TMDB' }))
    expect(domSnapshot()).toMatchSnapshot('tmdb short')
    fireEvent.change(screen.getByPlaceholderText('Search TMDB…'), { target: { value: 'brand' } })
    await screen.findByText('Brand New', {}, { timeout: 2000 })
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('tmdb results')
    fireEvent.click(screen.getByRole('button', { name: 'Library' }))
    expect((input as HTMLInputElement).value).toBe('brand')
    fireEvent.click(screen.getByRole('button', { name: 'TMDB' }))
    expect(log.filter((l) => l.includes('/tmdb/search'))).toMatchSnapshot('tmdb search requests')
  })

  test('tmdb mode empty, card click opens detail, closing the search clears query', async () => {
    mockApi({ tmdb: [] })
    await renderPage()
    await openModal()
    fireEvent.click(screen.getByRole('button', { name: 'TMDB' }))
    fireEvent.change(screen.getByPlaceholderText('Search TMDB…'), { target: { value: 'nothing' } })
    await screen.findByText(/No results for/, {}, { timeout: 2000 })
    expect(domSnapshot()).toMatchSnapshot('tmdb empty')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    fireEvent.click(screen.getByRole('button', { name: 'Search shows…' }))
    // The mode is retained across close/reopen; only the query is cleared.
    expect((await screen.findByPlaceholderText('Search TMDB…') as HTMLInputElement).value).toBe('')
  })

  test('tmdb card click opens the detail modal over the search modal', async () => {
    mockApi({ tmdb: [tmdbResult(900, 'Brand New')] })
    await renderPage()
    await openModal()
    fireEvent.click(screen.getByRole('button', { name: 'TMDB' }))
    fireEvent.change(screen.getByPlaceholderText('Search TMDB…'), { target: { value: 'brand' } })
    const title = await screen.findByText('Brand New', {}, { timeout: 2000 })
    fireEvent.click(title)
    await sleep(50)
    expect(domSnapshot()).toMatchSnapshot('detail over search')
  })

  test('search modal on a non-library tab renders in the page-level slot', async () => {
    mockApi()
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Data Quality/ }))
    await openModal()
    expect(domSnapshot()).toMatchSnapshot('modal over data tab')
  })
})
