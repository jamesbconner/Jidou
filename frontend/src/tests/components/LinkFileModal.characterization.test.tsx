import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { LinkFileModal } from '@/components/LinkFileModal'
import type { EpisodeList } from '@/types/api'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of LinkFileModal: DOM of both modes, the candidate/imported
 * pools, the live path verification, the config-seeded path state, each save
 * flow's request and the error display. Written before the pane extraction; it
 * must pass unchanged afterwards.
 */

const originalFetch = globalThis.fetch
let log: string[] = []
let bodies: Record<string, unknown[]> = {}

interface Routes {
  config?: unknown
  files?: unknown[]
  episodes?: unknown[]
  existing?: string[]
  patchStatus?: number
  linkStatus?: number
  assignStatus?: number
}
let routes: Routes = {}

beforeEach(() => {
  log = []
  bodies = {}
  routes = {}
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (init?.body) (bodies[`${init.method} ${url}`] ??= []).push(JSON.parse(String(init.body)))
    if (url.includes('/config')) return mockResponse(routes.config ?? {})
    if (url.includes('/files/verify-paths')) return mockResponse({ existing: routes.existing ?? [] })
    if (url.includes('/link-file'))
      return routes.linkStatus ? mockResponse({ detail: 'link boom' }, routes.linkStatus) : mockResponse({})
    if (url.includes('/assign-import'))
      return routes.assignStatus ? mockResponse({ detail: 'assign boom' }, routes.assignStatus) : mockResponse({})
    if (init?.method === 'PATCH' && url.includes('/files/'))
      return routes.patchStatus ? mockResponse({ detail: 'patch boom' }, routes.patchStatus) : mockResponse({ id: 1 })
    if (url.endsWith('/shows/1/episodes')) return mockResponse(routes.episodes ?? [])
    if (url.includes('/files?')) return mockResponse(routes.files ?? [])
    return mockResponse([])
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const episode = (over: Partial<EpisodeList> = {}): EpisodeList =>
  ({
    id: 10,
    show_id: 1,
    season_number: 1,
    episode_number: 8,
    name: 'Target Episode',
    file_tracked: false,
    tracked_source: null,
    tracked_filename: null,
    watched: false,
    backing_files: [],
    tracked_filename_display: null,
    ...over,
  }) as EpisodeList

const fileRow = (id: number, name: string, status: string, over: Record<string, unknown> = {}) => ({
  id,
  original_filename: name,
  remote_path: name,
  local_path: null,
  file_size: 1,
  status,
  show_id: 1,
  episode_id: null,
  ...over,
})

const mediaPaths = {
  tv: { container: '/media/tv', host: '/mnt/tv' },
  anime: { container: '/media/anime', host: '/mnt/anime' },
  movie: { container: '/media/movies', host: '/mnt/movies' },
}

function renderModal(over: { showLocalPath?: string | null; onClose?: () => void } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onClose = over.onClose ?? vi.fn()
  render(
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(LinkFileModal, {
        showId: 1,
        showLocalPath: over.showLocalPath ?? null,
        episode: episode(),
        onClose,
      }),
    ),
  )
  return onClose
}

const poolRoutes = (): Routes => ({
  config: { media_paths: mediaPaths },
  files: [
    fileRow(100, '/media/show/b-real.mkv', 'routed', { local_path: '/media/tv/b-real.mkv' }),
    fileRow(101, '/media/show/a-missing.mkv', 'matched', { local_path: '/media/tv/a-missing.mkv' }),
    fileRow(102, '/media/show/c-import.mkv', 'matched', { local_path: '/x/c.mkv', remote_path: 'synthetic-import://c' }),
    fileRow(103, '/media/show/d-inflight.mkv', 'downloading'),
    fileRow(104, '/media/show/e-taken.mkv', 'routed', { episode_id: 5 }),
    fileRow(105, '/media/show/f-nopath.mkv', 'unmatched'),
  ],
  episodes: [
    episode({ id: 20, episode_number: 2, name: 'Imp', file_tracked: true, tracked_source: 'import', tracked_filename: '/lib/z.mkv', tracked_filename_display: 'C:\\lib\\z.mkv' }),
    episode({ id: 21, episode_number: 3, name: 'Imp2', file_tracked: true, tracked_source: 'import', tracked_filename: '/lib/a.mkv' }),
    episode({ id: 22, episode_number: 4, name: 'Match', file_tracked: true, tracked_source: 'match', tracked_filename: '/lib/m.mkv' }),
  ],
  existing: ['/media/tv/b-real.mkv'],
})

describe('LinkFileModal characterization', () => {
  test('existing mode: pools, verification filter and request order', async () => {
    routes = poolRoutes()
    renderModal()
    await screen.findByText(/b-real\.mkv/)
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(bodies).toMatchSnapshot('bodies')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('existing mode: loading then empty message', async () => {
    routes = { config: {} }
    renderModal()
    expect(domSnapshot()).toMatchSnapshot('loading')
    await screen.findByText('No files available to link for this show.')
    expect(domSnapshot()).toMatchSnapshot('empty')
  })

  test('path mode seeds content type and folder from the show path once config loads', async () => {
    routes = { config: { media_paths: mediaPaths } }
    renderModal({ showLocalPath: '/media/anime/My Show (2020)' })
    fireEvent.click(await screen.findByRole('button', { name: 'Enter file path' }))
    await waitFor(() => expect((screen.getByPlaceholderText(/Show Name/) as HTMLInputElement).value).toBe('My Show (2020)/'))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('seeded dom')
  })

  test('path mode retains typed text across a mode round trip and does not reseed', async () => {
    routes = { config: { media_paths: mediaPaths } }
    renderModal({ showLocalPath: '/media/anime/My Show (2020)' })
    fireEvent.click(await screen.findByRole('button', { name: 'Enter file path' }))
    const input = await screen.findByPlaceholderText(/Show Name/)
    await waitFor(() => expect((input as HTMLInputElement).value).not.toBe(''))
    fireEvent.change(input, { target: { value: '/Typed/Season 01/ep.mkv' } })
    fireEvent.click(screen.getByLabelText('Movie'))
    fireEvent.click(screen.getByRole('button', { name: 'Pick existing file' }))
    fireEvent.click(screen.getByRole('button', { name: 'Enter file path' }))
    expect((screen.getByPlaceholderText(/Show Name/) as HTMLInputElement).value).toBe('/Typed/Season 01/ep.mkv')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('saving an existing file patches it and closes', async () => {
    routes = poolRoutes()
    const onClose = renderModal()
    await screen.findByText(/b-real\.mkv/)
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'e:100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(bodies).toMatchSnapshot('bodies')
  })

  test('saving an imported name assigns it', async () => {
    routes = poolRoutes()
    const onClose = renderModal()
    await screen.findByText(/b-real\.mkv/)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'i:/lib/a.mkv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(bodies).toMatchSnapshot('bodies')
  })

  test('saving a typed path links it; empty path keeps Save disabled', async () => {
    routes = { config: { media_paths: mediaPaths } }
    const onClose = renderModal()
    fireEvent.click(await screen.findByRole('button', { name: 'Enter file path' }))
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText(/Show Name/), { target: { value: '/Show/Season 01/x.mkv' } })
    await screen.findByText(/Show\/Season 01\/x\.mkv$/)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(bodies).toMatchSnapshot('bodies')
  })

  test.each([
    ['patch', { patchStatus: 500 }, 'existing'],
    ['link', { linkStatus: 500 }, 'path'],
    ['assign', { assignStatus: 500 }, 'import'],
  ])('%s failure shows the server error and keeps the modal open', async (_n, extra, flow) => {
    routes = { ...poolRoutes(), ...extra }
    const onClose = renderModal()
    await screen.findByText(/b-real\.mkv/)
    if (flow === 'existing') fireEvent.change(screen.getByRole('combobox'), { target: { value: 'e:100' } })
    if (flow === 'import') fireEvent.change(screen.getByRole('combobox'), { target: { value: 'i:/lib/a.mkv' } })
    if (flow === 'path') {
      fireEvent.click(screen.getByRole('button', { name: 'Enter file path' }))
      fireEvent.change(screen.getByPlaceholderText(/Show Name/), { target: { value: 'S/x.mkv' } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText(/boom/)
    expect(onClose).not.toHaveBeenCalled()
    expect(domSnapshot()).toMatchSnapshot('dom')
  })
})
