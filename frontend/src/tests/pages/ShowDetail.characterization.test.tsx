import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import ShowDetail from '@/pages/ShowDetail'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of the ShowDetail page: the rendered DOM (element order and
 * wrappers) for tv and movie shows, the request sequence on mount and on
 * interaction, and local state retained across tab switches. Written before the
 * presentational extraction; it must pass unchanged afterwards.
 */

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(
        MemoryRouter,
        { initialEntries: ['/shows/1'] },
        createElement(Routes, null, createElement(Route, { path: '/shows/:id', element: children })),
      ),
    )
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = vi.fn()
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const show = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  tmdb_id: 100,
  title: 'Test Show',
  media_type: 'tv',
  overview: 'A show about testing.',
  poster_path: '/poster.jpg',
  backdrop_path: null,
  vote_average: 7.5,
  vote_count: 10,
  release_date: '2020-01-01',
  content_type: 'anime',
  aliases: null,
  genres: null,
  local_path: '/media/anime/Test Show',
  detail_poster_path: null,
  active_episode_group_id: null,
  track_missing_episodes: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...overrides,
})

const ep = (overrides: Record<string, unknown>) => ({
  id: 1,
  show_id: 1,
  season_number: 1,
  episode_number: 1,
  name: 'Ep',
  overview: null,
  air_date: null,
  file_tracked: false,
  tracked_source: null,
  tracked_filename_display: null,
  watched: false,
  backing_files: [],
  ...overrides,
})

const episodes = [
  ep({ id: 11, episode_number: 1, name: 'Pilot', air_date: '2020-01-01', overview: 'First one.' }),
  ep({
    id: 12,
    episode_number: 2,
    name: 'Backed',
    file_tracked: true,
    tracked_source: 'match',
    backing_files: [
      { id: 501, filename: 'C:\\media\\Show.S01E02.mkv' },
      { id: 502, filename: '/media/Show.S01E02.alt.mkv' },
    ],
    watched: true,
  }),
  ep({
    id: 13,
    episode_number: 3,
    name: 'Imported',
    file_tracked: true,
    tracked_source: 'import',
    tracked_filename_display: '/media/imported/Show.S01E03.mkv',
  }),
  ep({ id: 21, season_number: 2, episode_number: 1, name: 'Season Two Opener', air_date: '2019-01-01' }),
]

interface Opts {
  show?: Record<string, unknown>
  episodes?: unknown[]
  files?: unknown[]
  watchlist?: unknown[]
  rssSubs?: unknown[]
  syncStatus?: number
  rssStubStatus?: number
}

function mockApi(opts: Opts = {}): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    log.push(`${method} ${url}`)
    if (url.includes('/sync')) {
      return opts.syncStatus ? mockResponse({ detail: 'sync boom' }, opts.syncStatus) : mockResponse({})
    }
    if (url.includes('/rss-stub'))
      return opts.rssStubStatus
        ? mockResponse({ detail: 'stub boom' }, opts.rssStubStatus)
        : mockResponse({ id: 88, name: 'Stub', show_id: 1, created_at: '2026-02-01T00:00:00Z' })
    if (url.includes('/shows/1/episodes')) return mockResponse(opts.episodes ?? [])
    if (url.includes('/shows/1/similar')) return mockResponse([])
    if (url.includes('/files?show_id=1')) return mockResponse(opts.files ?? [])
    if (url.includes('/shows/1')) return mockResponse(opts.show ?? show())
    if (url.includes('/config'))
      return mockResponse({ today: '2026-08-04', media_paths: {
          tv: { container: '/media/tv', host: '/mnt/tv' },
          anime: { container: '/media/anime', host: '/mnt/anime' },
          movie: { container: '/media/movies', host: '/mnt/movies' },
        },
      })
    if (url.includes('/rss/subscriptions')) return mockResponse(opts.rssSubs ?? [])
    if (url.includes('/rss/feeds')) return mockResponse([])
    if (url.includes('/watchlist')) {
      // Honour the by-show filter the way the API does (DF-18).
      const all = (opts.watchlist ?? []) as { show_id: number }[]
      const byShow = /[?&]show_id=(\d+)/.exec(url)
      return mockResponse(byShow ? all.filter((e) => e.show_id === Number(byShow[1])) : all)
    }
    return mockResponse([])
  })
  return log
}

async function renderPage() {
  render(createElement(ShowDetail), { wrapper: makeWrapper() })
  await screen.findByRole('button', { name: /^Action/ })
}

describe('ShowDetail characterization: tv show', () => {
  test('rich tv page DOM and mount request order', async () => {
    const log = mockApi({
      episodes,
      watchlist: [
        { id: 9, show_id: 1, status: 'planned', position: 0 },
        { id: 10, show_id: 2, status: 'planned', position: 1 },
      ],
      rssSubs: [
        { id: 3, name: 'Older', show_id: 1, created_at: '2026-01-01T00:00:00Z' },
        { id: 4, name: 'Newer', show_id: 1, created_at: '2026-03-01T00:00:00Z' },
      ],
    })
    await renderPage()
    await screen.findByText(/Season 1 \(3 episodes\)/)
    await screen.findByRole('button', { name: 'Edit RSS' })
    await screen.findByRole('button', { name: 'Queue #1' })
    await sleep(20)
    expect(log).toMatchSnapshot('mount requests')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('empty tv page (no path, no episodes, no watchlist)', async () => {
    mockApi({ show: show({ local_path: null, overview: null, content_type: null, track_missing_episodes: false }) })
    await renderPage()
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('all watched shows Mark Unwatched', async () => {
    mockApi({ episodes: [ep({ id: 1, name: 'A', watched: true }), ep({ id: 2, episode_number: 2, name: 'B', watched: true })] })
    await renderPage()
    await screen.findByRole('button', { name: 'Mark Unwatched' })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('missing tab then back; DOM per tab', async () => {
    mockApi({ episodes, show: show({ active_episode_group_id: 'g1' }) })
    await renderPage()
    await screen.findByText(/Season 1/)
    fireEvent.click(screen.getByRole('button', { name: /Missing Episodes/ }))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('missing tab')
    fireEvent.click(screen.getByRole('button', { name: /^Episodes \(/ }))
    await screen.findByText(/Season 1/)
    expect(domSnapshot()).toMatchSnapshot('episodes tab again')
  })

  test('sync failure surfaces inline and is retained after tab switch', async () => {
    const log = mockApi({ episodes, syncStatus: 500 })
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Sync Episodes' }))
    await screen.findByText('sync boom')
    expect(domSnapshot()).toMatchSnapshot('sync error')
    fireEvent.click(screen.getByRole('button', { name: /Missing Episodes/ }))
    fireEvent.click(screen.getByRole('button', { name: /^Episodes \(/ }))
    expect(screen.getByText('sync boom')).toBeInTheDocument()
    expect(log.filter((l) => l.includes('/sync'))).toHaveLength(1)
  })

  test('rss stub failure message; path modal; watched toggle request', async () => {
    const log = mockApi({ episodes, rssStubStatus: 500 })
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Add RSS' }))
    await screen.findByText('stub boom')
    expect(domSnapshot()).toMatchSnapshot('rss error')
    fireEvent.click(screen.getByRole('button', { name: 'Edit Path' }))
    await screen.findByRole('dialog')
    expect(domSnapshot()).toMatchSnapshot('path modal')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    const before = log.length
    fireEvent.click(screen.getAllByRole('switch', { hidden: true })[0])
    fireEvent.click(screen.getAllByRole('switch', { hidden: true })[1])
    await sleep(20)
    expect(log.slice(before).filter((l) => !l.startsWith('GET'))).toMatchSnapshot('toggle requests')
  })

  test('begin-rematch failure message under the episode list', async () => {
    mockApi({ episodes })
    const base = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes('begin-rematch')) return mockResponse({ detail: 'rematch boom' }, 500)
      return base(input, init)
    })
    await renderPage()
    // The sidebar's Fix Match now lives in the closed Action menu, so the only
    // Fix Match button on the page is the episode row's.
    fireEvent.click((await screen.findAllByRole('button', { name: 'Fix Match' }))[0])
    await screen.findByText('rematch boom')
    expect(domSnapshot()).toMatchSnapshot('rematch error')
  })
})

describe('ShowDetail characterization: movie', () => {
  test('movie with files', async () => {
    mockApi({
      show: show({ media_type: 'movie', content_type: 'movie' }),
      files: [
        { id: 1, original_filename: 'Movie.2020.mkv', status: 'routed' },
        { id: 2, original_filename: 'Movie.2020.part', status: 'downloading' },
      ],
    })
    await renderPage()
    await screen.findByText('Movie.2020.mkv')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('movie with no file', async () => {
    mockApi({ show: show({ media_type: 'movie', content_type: null, local_path: null }) })
    await renderPage()
    await screen.findByText(/No file linked yet/)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })
})
