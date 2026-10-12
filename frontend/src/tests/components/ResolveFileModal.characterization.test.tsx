import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ResolveFileModal } from '@/components/ResolveFileModal'
import type { FileRead, ShowSearchResult } from '@/types/api'

/**
 * Characterization of every ResolveFileModal search mode and step: the exact
 * request sequence, retained state across mode switches, and the rendered DOM.
 * Written before the candidate-search extraction so it pins the pre-refactor
 * behavior; it must pass unchanged afterwards.
 */

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, statusText: '', json: async () => body } as Response
}

const unmatchedFile = {
  id: 100,
  original_filename: 'Example.Show.S01E01.mkv',
  status: 'unmatched',
  parsed_show_name: 'Example Show',
} as unknown as FileRead

const config = {
  media_paths: {
    tv: { container: '/media/tv', host: '/mnt/tv' },
    anime: { container: '/media/anime', host: '/mnt/anime' },
    movie: { container: '/media/movies', host: '/mnt/movies' },
  },
}

const localShow: ShowSearchResult = {
  id: 7,
  tmdb_id: 700,
  title: 'Example Show',
  media_type: 'tv',
  content_type: 'anime',
  local_path: '/media/anime/Example Show (2019)',
  release_date: '2019-04-01',
  matched_on: 'title',
}

const suggestion = (id: number, title: string, media_type = 'tv', poster_path: string | null = null) => ({
  tmdb_id: id,
  title,
  media_type,
  overview: '',
  poster_path,
  first_air_date: '2019-04-01',
  vote_average: 7,
})

interface Routes {
  local?: ShowSearchResult[]
  suggestions?: unknown[]
  suggestionsStatus?: number
  search?: unknown[]
  details?: Record<string, unknown>
  detailsStatus?: number
  matchStatus?: number
}

/** Routes the modal's endpoints and returns the ordered request log. */
function mockApi(routes: Routes = {}): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (init?.method === 'POST' && url === '/api/files/100/match') {
      return routes.matchStatus
        ? mockResponse({ detail: 'match exploded' }, routes.matchStatus)
        : mockResponse({ id: 100 })
    }
    if (url === '/api/config') return mockResponse(config)
    if (url.startsWith('/api/shows/search?')) return mockResponse(routes.local ?? [])
    if (url.startsWith('/api/shows/tmdb/search?')) return mockResponse({ results: routes.search ?? [] })
    if (url.startsWith('/api/shows/tmdb/')) {
      return routes.detailsStatus
        ? mockResponse({ detail: 'no such id' }, routes.detailsStatus)
        : mockResponse(routes.details ?? {})
    }
    if (url.startsWith('/api/shows?')) return mockResponse([])
    if (url === '/api/files/100/tmdb-suggestions') {
      return routes.suggestionsStatus
        ? mockResponse({ detail: 'suggest exploded' }, routes.suggestionsStatus)
        : mockResponse({ query: 'Example Show', results: routes.suggestions ?? [] })
    }
    return mockResponse([])
  })
  return log
}

function postedBody(): Record<string, unknown> | null {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([u, i]) => String(u) === '/api/files/100/match' && i?.method === 'POST')
  return call ? JSON.parse(String(call[1]?.body)) : null
}

function renderModal() {
  return render(<ResolveFileModal file={unmatchedFile} onClose={() => {}} />, { wrapper: makeWrapper() })
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** The full rendered dialog, so any reorder or markup drift fails the snapshot. */
function dom(): string {
  return document.body.innerHTML
}

describe('ResolveFileModal characterization: suggestions mode', () => {
  test('mount fires config, suggestions, local search and library once each, in order', async () => {
    const log = mockApi({
      local: [localShow],
      suggestions: [suggestion(900, 'Brand New Show', 'tv', '/p.jpg'), suggestion(901, 'Some Movie', 'movie')],
    })
    renderModal()
    await screen.findByRole('button', { name: /Brand New Show/ })
    await screen.findByText('Example Show (2019)')
    await waitFor(() => expect(log.length).toBe(4))
    expect(log).toEqual([
      'GET /api/config',
      'GET /api/files/100/tmdb-suggestions',
      'GET /api/shows/search?query=Example%20Show&limit=6',
      'GET /api/shows?sort=title_asc&limit=10000',
    ])
    expect(dom()).toMatchSnapshot()
  })

  test('loading state shows the loading label and nothing else in the grid', async () => {
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}))
    renderModal()
    expect(await screen.findByText('Loading suggestions…')).toBeInTheDocument()
    expect(screen.queryByText('No results found.')).not.toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
  })

  test('empty suggestions show "No results found."', async () => {
    mockApi({ suggestions: [] })
    renderModal()
    expect(await screen.findByText('No results found.')).toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
  })

  test('a suggestions failure shows the error message and suppresses "No results found."', async () => {
    mockApi({ suggestionsStatus: 500 })
    renderModal()
    expect(await screen.findByText('suggest exploded')).toBeInTheDocument()
    expect(screen.queryByText('No results found.')).not.toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
  })

  test('matched_on labels render for folder, system name and alias matches', async () => {
    mockApi({
      local: [
        { ...localShow, id: 1, title: 'By Path', matched_on: 'path' },
        { ...localShow, id: 2, title: 'By Sys', matched_on: 'sys_name', local_path: null },
        { ...localShow, id: 3, title: 'By Alias', matched_on: 'alias' },
      ],
    })
    renderModal()
    expect(await screen.findByText('matched folder')).toBeInTheDocument()
    expect(screen.getByText('matched system name')).toBeInTheDocument()
    expect(screen.getByText('matched alias')).toBeInTheDocument()
    expect(screen.getByText('no local path set')).toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
  })
})

describe('ResolveFileModal characterization: confirm form', () => {
  test('picking a result renders the content-type and folder form; edits drive the posted payload', async () => {
    mockApi({ suggestions: [suggestion(900, 'Brand New: Show')] })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Brand New: Show/ }))

    const folder = await screen.findByPlaceholderText('Show Name')
    expect(screen.getByText('Selected: Brand New: Show (2019)')).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Anime' })).toBeChecked()
    expect(dom()).toMatchSnapshot()

    fireEvent.click(screen.getByRole('radio', { name: 'Tv' }))
    fireEvent.change(folder, { target: { value: 'Custom Folder' } })
    expect(screen.getByText('/mnt/tv/Custom Folder')).toBeInTheDocument()
    expect(dom()).toMatchSnapshot()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    await waitFor(() => expect(postedBody()).not.toBeNull())
    expect(postedBody()).toEqual({
      tmdb_id: 900,
      tmdb_media_type: 'tv',
      local_path: '/media/tv/Custom Folder',
      content_type: 'tv',
    })
  })

  test('picking a movie snaps the content type to movie', async () => {
    mockApi({ suggestions: [suggestion(901, 'Some Movie', 'movie')] })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Some Movie/ }))
    await screen.findByPlaceholderText('Show Name')
    expect(screen.getByRole('radio', { name: 'Movie' })).toBeChecked()
  })

  test('a result with no title defaults the folder to "Untitled"; clearing it requires a name before confirming', async () => {
    mockApi({ suggestions: [suggestion(902, '')] })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /No image/ }))
    const folder = await screen.findByPlaceholderText('Show Name')
    expect(folder).toHaveValue('Untitled')
    expect(screen.queryByText(/This result has no title/)).not.toBeInTheDocument()

    fireEvent.change(folder, { target: { value: '   ' } })
    expect(await screen.findByText(/This result has no title/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm match' })).toBeDisabled()
    expect(dom()).toMatchSnapshot()

    fireEvent.change(folder, { target: { value: 'Typed Name' } })
    expect(screen.getByRole('button', { name: 'Confirm match' })).toBeEnabled()
  })

  test('picking a different result re-derives the folder, discarding edits', async () => {
    mockApi({ suggestions: [suggestion(900, 'First Show'), suggestion(903, 'Second Show')] })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /First Show/ }))
    fireEvent.change(await screen.findByPlaceholderText('Show Name'), { target: { value: 'Edited' } })
    fireEvent.click(screen.getByRole('button', { name: /Second Show/ }))
    expect(screen.getByPlaceholderText('Show Name')).toHaveValue('Second Show')
  })

  test('selecting a local show then a TMDB result swaps the selection panel', async () => {
    mockApi({ local: [localShow], suggestions: [suggestion(900, 'Brand New Show')] })
    renderModal()
    fireEvent.click(await screen.findByText('Example Show (2019)'))
    expect(await screen.findByText(/In your library — the file will be assigned/)).toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
    fireEvent.click(screen.getByRole('button', { name: /Brand New Show/ }))
    expect(await screen.findByPlaceholderText('Show Name')).toBeInTheDocument()
    expect(screen.queryByText(/In your library — the file/)).not.toBeInTheDocument()
  })

  test('a failed match shows the error and re-enables the form', async () => {
    mockApi({ suggestions: [suggestion(900, 'Brand New Show')], matchStatus: 500 })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Brand New Show/ }))
    fireEvent.click(await screen.findByRole('button', { name: 'Confirm match' }))
    expect(await screen.findByText('match exploded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm match' })).toBeEnabled()
    expect(dom()).toMatchSnapshot()
  })

  test('Reset for auto re-match posts an empty payload', async () => {
    mockApi()
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'Reset for auto re-match' }))
    await waitFor(() => expect(postedBody()).not.toBeNull())
    expect(postedBody()).toEqual({})
  })
})

describe('ResolveFileModal characterization: title (refine) mode', () => {
  const found = [
    { id: 11, name: 'Found Show', media_type: 'tv', overview: 'o', poster_path: null, first_air_date: '2020-01-01', vote_average: 1 },
    { id: 12, title: 'Found Movie', media_type: 'movie', overview: 'o', poster_path: '/m.jpg', release_date: '2021-02-02', vote_average: 1 },
    { id: 13, name: 'A Person', media_type: 'person', overview: '', poster_path: null, vote_average: 0 },
  ]

  test('refine seeds the query, searches after the debounce, filters non-tv/movie, and drops suggestions', async () => {
    const log = mockApi({ suggestions: [suggestion(900, 'Stale Suggestion')], search: found })
    renderModal()
    await screen.findByRole('button', { name: /Stale Suggestion/ })

    fireEvent.click(screen.getByRole('button', { name: 'refine search' }))
    expect(screen.getByPlaceholderText('Search TMDB...')).toHaveValue('Example Show')
    expect(await screen.findByRole('button', { name: /Found Show/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Found Movie/ })).toBeInTheDocument()
    expect(screen.queryByText('A Person')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Stale Suggestion/ })).not.toBeInTheDocument()
    expect(log.filter((l) => l.includes('/tmdb/search'))).toEqual([
      'GET /api/shows/tmdb/search?query=Example%20Show&media_type=multi',
    ])
    // Suggestions are fetched once at mount and never again by the mode switch.
    expect(log.filter((l) => l.includes('tmdb-suggestions'))).toHaveLength(1)
    expect(dom()).toMatchSnapshot()
  })

  test('rapid typing debounces to a single request for the final value; <2 chars sends none', async () => {
    const log = mockApi({ search: found })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'refine search' }))
    await screen.findByRole('button', { name: /Found Show/ })
    log.length = 0

    const input = screen.getByPlaceholderText('Search TMDB...')
    fireEvent.change(input, { target: { value: 'Ab' } })
    await sleep(100)
    fireEvent.change(input, { target: { value: 'Abc' } })
    await waitFor(() => expect(log.some((l) => l.includes('/tmdb/search?query=Abc'))).toBe(true))
    expect(log.filter((l) => l.includes('/tmdb/search'))).toEqual([
      'GET /api/shows/tmdb/search?query=Abc&media_type=multi',
    ])
    expect(log.filter((l) => l.includes('/shows/search?'))).toEqual([
      'GET /api/shows/search?query=Abc&limit=6',
    ])

    log.length = 0
    fireEvent.change(input, { target: { value: 'A' } })
    await sleep(450)
    expect(log).toEqual([])
    expect(screen.getByPlaceholderText('Search TMDB...')).toHaveValue('A')
  })

  test('back to suggestions restores the suggestion grid and refine re-seeds the parsed name', async () => {
    mockApi({ suggestions: [suggestion(900, 'Stale Suggestion')], search: found })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'refine search' }))
    fireEvent.change(screen.getByPlaceholderText('Search TMDB...'), { target: { value: 'Something Else' } })
    fireEvent.click(screen.getByRole('button', { name: 'back to suggestions' }))
    expect(await screen.findByRole('button', { name: /Stale Suggestion/ })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Search TMDB...')).not.toBeInTheDocument()
    expect(dom()).toMatchSnapshot()

    fireEvent.click(screen.getByRole('button', { name: 'refine search' }))
    expect(screen.getByPlaceholderText('Search TMDB...')).toHaveValue('Example Show')
  })

  test('a selection made in one mode survives switching modes', async () => {
    mockApi({ suggestions: [suggestion(900, 'Brand New Show')], search: found })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Brand New Show/ }))
    fireEvent.change(await screen.findByPlaceholderText('Show Name'), { target: { value: 'Kept Edit' } })
    fireEvent.click(screen.getByRole('button', { name: 'refine search' }))
    await screen.findByRole('button', { name: /Found Show/ })
    expect(screen.getByPlaceholderText('Show Name')).toHaveValue('Kept Edit')
    expect(screen.getByText('Selected: Brand New Show (2019)')).toBeInTheDocument()
  })
})

describe('ResolveFileModal characterization: TMDB ID mode', () => {
  const detail = { id: 1668, name: 'Detail Show', overview: 'o', poster_path: '/d.jpg', first_air_date: '2004-09-22', vote_average: 8 }

  test('only a numeric id triggers a lookup, with the chosen media type', async () => {
    const log = mockApi({ suggestions: [suggestion(900, 'Stale Suggestion')], details: detail })
    renderModal()
    await screen.findByRole('button', { name: /Stale Suggestion/ })

    fireEvent.click(screen.getByRole('button', { name: 'search by TMDB ID' }))
    expect(screen.queryByRole('button', { name: /Stale Suggestion/ })).not.toBeInTheDocument()
    expect(await screen.findByText('No results found.')).toBeInTheDocument()
    expect(dom()).toMatchSnapshot()

    const input = screen.getByPlaceholderText('TMDB ID, e.g. 1668')
    fireEvent.change(input, { target: { value: '0' } })
    await sleep(50)
    expect(log.filter((l) => l.startsWith('GET /api/shows/tmdb/'))).toEqual([])

    fireEvent.change(input, { target: { value: '1668' } })
    expect(await screen.findByRole('button', { name: /Detail Show/ })).toBeInTheDocument()
    expect(log.filter((l) => l.startsWith('GET /api/shows/tmdb/'))).toEqual([
      'GET /api/shows/tmdb/1668?media_type=tv',
    ])
    expect(log.filter((l) => l.includes('tmdb-suggestions'))).toHaveLength(1)
    expect(log.filter((l) => l.includes('/shows/search?'))).toEqual([
      'GET /api/shows/search?query=Example%20Show&limit=6',
    ])
    expect(dom()).toMatchSnapshot()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'movie' } })
    await waitFor(() => expect(log).toContain('GET /api/shows/tmdb/1668?media_type=movie'))
    // The movie lookup carries the chosen media type onto the candidate and the snapped content type.
    fireEvent.click(await screen.findByRole('button', { name: /Detail Show/ }))
    expect(await screen.findByRole('radio', { name: 'Movie' })).toBeChecked()
    expect(screen.getByText(/· movie/)).toBeInTheDocument()
  })

  test('a failed lookup shows the lookup error instead of "No results found."', async () => {
    mockApi({ detailsStatus: 404 })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'search by TMDB ID' }))
    fireEvent.change(screen.getByPlaceholderText('TMDB ID, e.g. 1668'), { target: { value: '5' } })
    expect(await screen.findByText('no such id')).toBeInTheDocument()
    expect(screen.queryByText('No results found.')).not.toBeInTheDocument()
    expect(dom()).toMatchSnapshot()
  })

  test('a suggestions error does not leak into TMDB ID mode', async () => {
    mockApi({ suggestionsStatus: 500 })
    renderModal()
    expect(await screen.findByText('suggest exploded')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'search by TMDB ID' }))
    expect(await screen.findByText('No results found.')).toBeInTheDocument()
    expect(screen.queryByText('suggest exploded')).not.toBeInTheDocument()
  })

  test('the typed id and media type are retained across back-to-suggestions', async () => {
    mockApi({ details: detail })
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'search by TMDB ID' }))
    fireEvent.change(screen.getByPlaceholderText('TMDB ID, e.g. 1668'), { target: { value: '1668' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'movie' } })
    await screen.findByRole('button', { name: /Detail Show/ })
    fireEvent.click(screen.getByRole('button', { name: 'back to suggestions' }))
    fireEvent.click(screen.getByRole('button', { name: 'search by TMDB ID' }))
    expect(screen.getByPlaceholderText('TMDB ID, e.g. 1668')).toHaveValue(1668)
    expect(screen.getByRole('combobox')).toHaveValue('movie')
    expect(await screen.findByRole('button', { name: /Detail Show/ })).toBeInTheDocument()
  })
})
