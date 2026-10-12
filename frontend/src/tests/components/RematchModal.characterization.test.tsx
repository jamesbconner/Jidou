import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { RematchModal } from '@/components/RematchModal'
import type { FileRead } from '@/types/api'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of RematchModal: both modes, every selection state (library
 * hit with/without a path, TMDB hit new/existing/no-path), the editable folder
 * state, the match-then-route request order and each error line. Written before
 * the pane extraction; it must pass unchanged afterwards.
 */

const originalFetch = globalThis.fetch
let log: string[] = []
let bodies: Record<string, unknown[]> = {}

interface Routes {
  local?: unknown[]
  tmdb?: unknown[]
  index?: unknown[]
  matchStatus?: number
  routeStatus?: number
}
let routes: Routes = {}

const mediaPaths = {
  tv: { container: '/media/tv', host: '/mnt/tv' },
  anime: { container: '/media/anime', host: '/mnt/anime' },
  movie: { container: '/media/movies', host: '/mnt/movies' },
}

beforeEach(() => {
  log = []
  bodies = {}
  routes = {}
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (init?.body) (bodies[`${init.method} ${url}`] ??= []).push(JSON.parse(String(init.body)))
    if (url === '/api/config') return mockResponse({ media_paths: mediaPaths })
    if (url.includes('/files/100/match'))
      return routes.matchStatus ? mockResponse({ detail: 'match boom' }, routes.matchStatus) : mockResponse({ id: 100 })
    if (url.includes('/tasks/trigger'))
      return routes.routeStatus ? mockResponse({ detail: 'route boom' }, routes.routeStatus) : mockResponse({ id: 1 })
    if (url.startsWith('/api/shows/search?')) return mockResponse(routes.local ?? [])
    if (url.startsWith('/api/shows/tmdb/search?'))
      return mockResponse({ results: routes.tmdb ?? [], total_results: 0, total_pages: 1, page: 1 })
    if (url.startsWith('/api/shows?')) return mockResponse(routes.index ?? [])
    return mockResponse([])
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const file = (over: Record<string, unknown> = {}) =>
  ({
    id: 100,
    original_filename: 'Example.Show.S01E01.mkv',
    status: 'unmatched',
    parsed_show_name: 'Example Show',
    show_id: null,
    show: null,
    ...over,
  }) as unknown as FileRead

const hit = (id: number, title: string, local_path: string | null, matched_on = 'title') => ({
  id,
  tmdb_id: id * 100,
  title,
  media_type: 'tv',
  content_type: 'anime',
  local_path,
  matched_on,
})

const tmdb = (id: number, name: string | null, media_type: string, over: Record<string, unknown> = {}) => ({
  id,
  name,
  title: name === null ? null : undefined,
  media_type,
  overview: '',
  poster_path: id % 2 ? '/p.jpg' : null,
  first_air_date: '2021-05-01',
  vote_average: 7,
  ...over,
})

function renderModal(f: FileRead = file(), onClose: () => void = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(createElement(QueryClientProvider, { client: qc }, createElement(RematchModal, { file: f, onClose })))
  return onClose
}

const tmdbRoutes = (): Routes => ({
  tmdb: [
    tmdb(1, 'New Show', 'tv'),
    tmdb(2, 'A Movie', 'movie', { first_air_date: undefined, release_date: '2018-02-02' }),
    tmdb(3, 'Person', 'person'),
    tmdb(5, 'Known Show', 'tv'),
    tmdb(7, 'Known No Path', 'tv'),
    tmdb(9, null, 'tv', { title: undefined }),
  ],
  index: [
    { id: 55, tmdb_id: 5, media_type: 'tv', title: 'Known Show', local_path: '/media/tv/Known' },
    { id: 77, tmdb_id: 7, media_type: 'tv', title: 'Known No Path', local_path: null },
  ],
})

describe('RematchModal characterization: tmdb mode', () => {
  test('initial DOM, loading, results and request order', async () => {
    routes = tmdbRoutes()
    renderModal(file({ show_id: 3, show: { id: 3, title: 'Old Show' } }))
    expect(domSnapshot()).toMatchSnapshot('initial')
    await screen.findByText('New Show')
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('results')
  })

  test('file assigned to an unknown show title falls back to the id', () => {
    routes = tmdbRoutes()
    renderModal(file({ show_id: 9, show: null }))
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('no results message', async () => {
    routes = { tmdb: [] }
    renderModal()
    await screen.findByText('No results.')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('selecting a new tmdb result shows content type + folder, editable and live path', async () => {
    routes = tmdbRoutes()
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /New Show/ }))
    expect(domSnapshot()).toMatchSnapshot('selected new')
    fireEvent.click(screen.getByLabelText('Anime'))
    fireEvent.change(screen.getByPlaceholderText('Show Name'), { target: { value: 'Custom Folder' } })
    expect(domSnapshot()).toMatchSnapshot('edited')
    fireEvent.change(screen.getByPlaceholderText('Show Name'), { target: { value: '   ' } })
    expect(domSnapshot()).toMatchSnapshot('blank folder')
  })

  test('selecting a movie snaps the content type; no-title result asks for a folder', async () => {
    routes = tmdbRoutes()
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /A Movie/ }))
    expect((screen.getByLabelText('Movie') as HTMLInputElement).checked).toBe(true)
    const dated = screen.getAllByRole('button', { name: /2021/ })
    fireEvent.click(dated[dated.length - 1])
    expect(domSnapshot()).toMatchSnapshot('untitled selected')
  })

  test('already-in-library selections (with and without a local path)', async () => {
    routes = tmdbRoutes()
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Known Show/ }))
    expect(domSnapshot()).toMatchSnapshot('known with path')
    expect(screen.getByRole('button', { name: 'Match & Route' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: /Known No Path/ }))
    expect(domSnapshot()).toMatchSnapshot('known without path')
    expect(screen.getByRole('button', { name: 'Match & Route' })).toBeDisabled()
  })

  test('confirm a new show: match payload then route, then close', async () => {
    routes = tmdbRoutes()
    const onClose = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /New Show/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Match & Route' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(log.filter((l) => l.startsWith('POST'))).toMatchSnapshot('posts')
    expect(bodies).toMatchSnapshot('bodies')
  })

  test('confirm an existing show reuses its id', async () => {
    routes = tmdbRoutes()
    const onClose = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /Known Show/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Match & Route' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(bodies).toMatchSnapshot('bodies')
  })

  test('match failure shows its error and skips routing; route failure shows its own', async () => {
    routes = { ...tmdbRoutes(), matchStatus: 500 }
    const onClose = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /New Show/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Match & Route' }))
    await screen.findByText('match boom')
    expect(log.some((l) => l.includes('/tasks/trigger'))).toBe(false)
    expect(onClose).not.toHaveBeenCalled()
    expect(domSnapshot()).toMatchSnapshot('match error')
  })

  test('route failure after a successful match', async () => {
    routes = { ...tmdbRoutes(), routeStatus: 500 }
    const onClose = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /New Show/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Match & Route' }))
    await screen.findByText('route boom')
    expect(onClose).not.toHaveBeenCalled()
    expect(domSnapshot()).toMatchSnapshot('route error')
  })
})

describe('RematchModal characterization: library mode', () => {
  test('switching clears the query, selection and error; results show paths and warnings', async () => {
    routes = { ...tmdbRoutes(), local: [hit(7, 'Has Path', '/media/anime/Has Path'), hit(8, 'No Path', null, 'alias')] }
    renderModal()
    fireEvent.click(await screen.findByRole('button', { name: /New Show/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Library' }))
    expect(domSnapshot()).toMatchSnapshot('after switch')
    fireEvent.change(screen.getByPlaceholderText('Search your library…'), { target: { value: 'path' } })
    await screen.findByText('Has Path')
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('results')
    fireEvent.click(screen.getByRole('button', { name: /No Path/ }))
    expect(domSnapshot()).toMatchSnapshot('no path selected')
    expect(screen.getByRole('button', { name: 'Match & Route' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: /Has Path/ }))
    expect(screen.getByRole('button', { name: 'Match & Route' })).toBeEnabled()
    expect(log.filter((l) => l.includes('/shows/search'))).toMatchSnapshot('library requests')
  })

  test('library confirm posts show_id then routes; empty search says none found', async () => {
    routes = { local: [hit(7, 'Has Path', '/media/anime/Has Path')] }
    const onClose = renderModal()
    fireEvent.click(screen.getByRole('button', { name: 'Library' }))
    fireEvent.change(screen.getByPlaceholderText('Search your library…'), { target: { value: 'path' } })
    fireEvent.click(await screen.findByRole('button', { name: /Has Path/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Match & Route' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(bodies).toMatchSnapshot('bodies')
  })

  test('no library shows found', async () => {
    routes = { local: [] }
    renderModal()
    fireEvent.click(screen.getByRole('button', { name: 'Library' }))
    fireEvent.change(screen.getByPlaceholderText('Search your library…'), { target: { value: 'zz' } })
    await screen.findByText('No library shows found.')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })
})
