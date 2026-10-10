import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ResolveFileModal } from '@/components/ResolveFileModal'
import type { FileRead, ShowList, ShowSearchResult } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
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

// A remake whose folder carries a year suffix that the TMDB title does not.
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

const tmdbSuggestion = {
  tmdb_id: 700,
  title: 'Example Show',
  media_type: 'tv',
  overview: '',
  poster_path: null,
  first_air_date: '2019-04-01',
  vote_average: 7,
}

interface Routes {
  local?: ShowSearchResult[]
  library?: Partial<ShowList>[]
  suggestions?: unknown[]
}

function mockApi({ local = [], library = [], suggestions = [] }: Routes) {
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    if (init?.method === 'POST' && url === '/api/files/100/match') return mockResponse({ id: 100 })
    if (url === '/api/config') return mockResponse(config)
    if (url.startsWith('/api/shows/search?')) return mockResponse(local)
    if (url.startsWith('/api/shows?')) return mockResponse(library)
    if (url === '/api/files/100/tmdb-suggestions') {
      return mockResponse({ query: 'Example Show', results: suggestions })
    }
    return mockResponse([])
  })
}

function postedMatchBody(): Record<string, unknown> | null {
  const call = vi
    .mocked(fetch)
    .mock.calls.find(([u, i]) => String(u) === '/api/files/100/match' && i?.method === 'POST')
  return call ? JSON.parse(String(call[1]?.body)) : null
}

function renderModal() {
  render(<ResolveFileModal file={unmatchedFile} onClose={() => {}} />, { wrapper: makeWrapper() })
}

describe('ResolveFileModal local + TMDB matching', () => {
  test('lists local library matches and assigns by show_id using the existing folder', async () => {
    mockApi({ local: [localShow] })
    renderModal()

    fireEvent.click(await screen.findByText('Example Show (2019)'))

    // The existing, year-suffixed folder is shown and cannot be edited away.
    expect(await screen.findByText('/mnt/anime/Example Show (2019)', { selector: 'div.break-all' })).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Show Name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    await waitFor(() => expect(postedMatchBody()).not.toBeNull())
    expect(postedMatchBody()).toEqual({ show_id: 7 })
  })

  test('a TMDB pick that is already in the library reuses the existing folder', async () => {
    mockApi({
      suggestions: [tmdbSuggestion],
      library: [
        { id: 7, tmdb_id: 700, media_type: 'tv', title: 'Example Show', local_path: '/media/anime/Example Show (2019)' },
      ],
    })
    renderModal()

    fireEvent.click(await screen.findByRole('button', { name: /Example Show/ }))

    expect(await screen.findByText(/Already in your library as/)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText('Show Name')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    await waitFor(() => expect(postedMatchBody()).not.toBeNull())
    // show_id, not tmdb_id/local_path: the derived "Example Show" folder is never sent.
    expect(postedMatchBody()).toEqual({ show_id: 7 })
  })

  test('a TMDB pick that is not in the library still derives a folder from the title', async () => {
    mockApi({ suggestions: [{ ...tmdbSuggestion, tmdb_id: 900, title: 'Brand New Show' }] })
    renderModal()

    fireEvent.click(await screen.findByRole('button', { name: /Brand New Show/ }))
    const folder = await screen.findByPlaceholderText('Show Name')
    expect(folder).toHaveValue('Brand New Show')

    fireEvent.click(screen.getByRole('button', { name: 'Confirm match' }))
    await waitFor(() => expect(postedMatchBody()).not.toBeNull())
    expect(postedMatchBody()).toMatchObject({
      tmdb_id: 900,
      tmdb_media_type: 'tv',
      local_path: '/media/anime/Brand New Show',
    })
    expect(postedMatchBody()).not.toHaveProperty('show_id')
  })

  test('a local show with no folder cannot be confirmed', async () => {
    mockApi({ local: [{ ...localShow, local_path: null }] })
    renderModal()

    fireEvent.click(await screen.findByText('Example Show (2019)'))

    expect(await screen.findByText(/has no local path/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm match' })).toBeDisabled()
  })
})
