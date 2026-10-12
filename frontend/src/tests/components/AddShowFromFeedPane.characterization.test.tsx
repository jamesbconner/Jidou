import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { AddShowFromFeedPane } from '@/components/AddShowFromFeedPane'
import type { FeedEntryGroupRead, RssFeedRead } from '@/types/api'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of AddShowFromFeedPane: the rendered DOM of every pane state
 * (search, picked, suggested, error, each outcome) and the ordered request log.
 * Written before the section extraction; it must pass unchanged afterwards.
 */

const originalFetch = globalThis.fetch
let log: string[] = []
let bodies: Record<string, unknown[]> = {}

interface Routes {
  library?: unknown[]
  libraryIndex?: unknown[]
  tmdb?: unknown[]
  suggestStatus?: number
  addStatus?: number
  addBody?: unknown
}
let routes: Routes = {}

const report = {
  matched_titles: ['[G] Brand New Show - 05 (1080p).mkv'],
  unmatched_titles: ['[G] Brand New Show - 06 (720p).mkv'],
  total: 2,
}
const suggestion = {
  regex_include: 'Brand.New.Show.*1080p',
  regex_exclude: 'FRENCH',
  model: 'm',
  cached: false,
  match: report,
}
const addResult = {
  show: { id: 42, title: 'Brand New Show', status: null, poster_path: null },
  show_created: false,
  subscription: null,
  subscription_created: true,
  adopted_stub: false,
  alias_added: true,
  dry_run: false,
}

beforeEach(() => {
  log = []
  bodies = {}
  routes = {}
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (init?.body) (bodies[url] ??= []).push(JSON.parse(String(init.body)))
    if (url.includes('/suggest-regex'))
      return routes.suggestStatus
        ? mockResponse({ detail: 'LLM provider is not configured' }, routes.suggestStatus)
        : mockResponse(suggestion)
    if (url.includes('/test-regex')) return mockResponse(report)
    if (url.includes('/add-show'))
      return routes.addStatus
        ? mockResponse({ detail: 'Show not found' }, routes.addStatus)
        : mockResponse(routes.addBody ?? addResult)
    if (url.includes('/shows/tmdb/search'))
      return mockResponse({ results: routes.tmdb ?? [], total_results: 0, total_pages: 1, page: 1 })
    if (url.includes('/shows/search')) return mockResponse(routes.library ?? [])
    if (url.includes('/shows?')) return mockResponse(routes.libraryIndex ?? [])
    return mockResponse([])
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const feed = { id: 7, name: 'Example Tracker', url: 'https://t.example/rss', active: true } as RssFeedRead
const group = (overrides: Partial<FeedEntryGroupRead> = {}): FeedEntryGroupRead =>
  ({
    parsed_name: 'Brand New Show',
    entry_count: 3,
    season_min: 1,
    season_max: 1,
    episode_min: 5,
    episode_max: 6,
    sample_titles: [],
    library_show: null,
    existing_subscription_id: null,
    ...overrides,
  }) as FeedEntryGroupRead
const libraryGroup = () =>
  group({ library_show: { id: 42, title: 'Brand New Show', status: null, poster_path: null } })

const tmdbHit = (id: number, name: string, media_type: string) => ({
  id,
  name,
  title: null,
  media_type,
  overview: '',
  poster_path: null,
  first_air_date: '2022-03-01',
  vote_average: 7,
})

function renderPane(g: FeedEntryGroupRead, handlers: { onDone?: () => void; onAdded?: () => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AddShowFromFeedPane feed={feed} group={g} {...handlers} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('AddShowFromFeedPane characterization', () => {
  test('nothing picked: search results from library and TMDB (mixed, deduped)', async () => {
    routes = {
      library: [{ id: 42, tmdb_id: 1, title: 'Brand New Show', media_type: 'tv', matched_on: 'title' }],
      libraryIndex: [{ id: 43, tmdb_id: 901, media_type: 'tv', title: 'Indexed Show' }],
      tmdb: [
        tmdbHit(900, 'Brand New TMDB', 'tv'),
        tmdbHit(901, 'Indexed Show', 'tv'),
        tmdbHit(902, 'Some Movie', 'movie'),
        tmdbHit(903, 'Person', 'person'),
      ],
    }
    renderPane(group(), { onDone: () => {} })
    await screen.findByRole('option', { name: /Brand New TMDB/ })
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('library pick: suggestion fills the filter and previews the match', async () => {
    renderPane(libraryGroup())
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('suggested dom')
    expect(log).toMatchSnapshot('suggest requests')
    expect(bodies).toMatchSnapshot('request bodies')
  })

  test('hand edit previews after the debounce; checkbox toggles retest', async () => {
    renderPane(libraryGroup())
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    fireEvent.change(screen.getByLabelText('Include regex'), { target: { value: 'Edited' } })
    await sleep(700)
    fireEvent.click(screen.getByLabelText('Ignore case (include)'))
    await sleep(700)
    expect(log).toMatchSnapshot('requests')
    expect(bodies).toMatchSnapshot('request bodies')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('tmdb pick shows the will-be-added note and the name placeholder', async () => {
    routes = { tmdb: [tmdbHit(900, 'Brand New TMDB', 'tv')] }
    renderPane(group())
    fireEvent.click(await screen.findByRole('option', { name: /Brand New TMDB/ }))
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('suggest failure keeps the form with the error and the empty-include caveat', async () => {
    routes = { suggestStatus: 422 }
    renderPane(libraryGroup())
    await screen.findByRole('alert')
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('re-suggest sends the previous include', async () => {
    renderPane(libraryGroup())
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    fireEvent.click(await screen.findByRole('button', { name: 'Re-suggest' }))
    await sleep(50)
    expect(bodies).toMatchSnapshot('request bodies')
  })

  test('add failure shows the server error and keeps the form', async () => {
    routes = { addStatus: 404 }
    renderPane(libraryGroup())
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))
    await screen.findByText('Show not found')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test.each([
    ['created', { ...addResult }, false],
    ['created and enabled', { ...addResult, show_created: true }, true],
    ['adopted stub', { ...addResult, subscription_created: false, adopted_stub: true, alias_added: false }, true],
    ['already subscribed', { ...addResult, subscription_created: false, adopted_stub: false, alias_added: false }, false],
    ['no show returned', { ...addResult, show: null }, false],
  ])('outcome: %s', async (_name, body, enable) => {
    routes = { addBody: body }
    const onAdded = vi.fn()
    renderPane(libraryGroup(), { onDone: () => {}, onAdded })
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    if (enable) fireEvent.click(screen.getByLabelText(/Enable now/))
    fireEvent.change(screen.getByLabelText('Subscription name'), { target: { value: '  Custom  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))
    await screen.findByRole('status')
    expect(onAdded).toHaveBeenCalledTimes(1)
    expect(bodies[Object.keys(bodies).find((u) => u.includes('/add-show')) ?? '']).toMatchSnapshot('add body')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('outcome without onDone omits the Close button', async () => {
    renderPane(libraryGroup())
    await screen.findByDisplayValue('Brand.New.Show.*1080p')
    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))
    await screen.findByRole('status')
    expect(screen.queryByRole('button', { name: 'Close' })).toBeNull()
  })
})
