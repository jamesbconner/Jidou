import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import ShowDetail from '@/pages/ShowDetail'
import type { ShowRead } from '@/types/api'

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
    headers: { get: () => null } as unknown as Headers,
    json: async () => body,
  } as unknown as Response
}

function baseShow(overrides: Partial<ShowRead> = {}): ShowRead {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Test Show',
    media_type: 'tv',
    overview: null,
    poster_path: null,
    backdrop_path: null,
    vote_average: null,
    vote_count: 0,
    release_date: null,
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

function mockShowDetail(initial: ShowRead, opts: { files?: unknown[] } = {}) {
  let show = initial
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (method === 'PATCH' && url.includes('/shows/1')) {
      const patch = JSON.parse(String(init?.body)) as Partial<ShowRead>
      show = { ...show, ...patch }
      return mockResponse(show)
    }
    if (url.includes('/shows/1/episodes')) return mockResponse([])
    if (url.includes('/shows/1/scan-local-movie-file')) return mockResponse([])
    if (url.includes('/files?show_id=1')) return mockResponse(opts.files ?? [])
    if (url.includes('/shows/1')) return mockResponse(show)
    if (url.includes('/config')) return mockResponse({ today: '2026-08-04' })
    if (url.includes('/rss/subscriptions')) return mockResponse([])
    if (url.includes('/rss/feeds')) return mockResponse([])
    if (url.includes('/watchlist')) return mockResponse([])
    return mockResponse([])
  })
}

describe('ShowDetail — Ignore Missing Eps toggle', () => {
  test('shows "Ignore Missing Eps" for a tracked show and toggles it off on click', async () => {
    mockShowDetail(baseShow({ track_missing_episodes: true }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const button = await screen.findByRole('button', { name: 'Ignore Missing Eps' })
    fireEvent.click(button)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Track Missing Eps' })).toBeInTheDocument()
    })

    const patchCall = vi
      .mocked(fetch)
      .mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(patchCall).toBeDefined()
    expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ track_missing_episodes: false })
  })

  test('shows "Track Missing Eps" for an ignored show', async () => {
    mockShowDetail(baseShow({ track_missing_episodes: false }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    expect(await screen.findByRole('button', { name: 'Track Missing Eps' })).toBeInTheDocument()
  })
})

describe('ShowDetail — files fetch', () => {
  test('requests show_ignored=true so ignored files linked to the show still appear', async () => {
    // useFilesByShow only fires for movie-type shows (see isMovie in ShowDetail.tsx).
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }))
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    await waitFor(() => {
      const call = vi.mocked(fetch).mock.calls.find(([input]) => String(input).includes('/files?show_id=1'))
      expect(call).toBeDefined()
      expect(String(call?.[0])).toContain('show_ignored=true')
    })
  })
})

describe('ShowDetail — Movie file actions', () => {
  test('renders Fix Match button for a matched movie file', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'matched', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    expect(row.getByRole('button', { name: 'Fix Match' })).toBeInTheDocument()
  })

  test('does not render Fix Match button while the movie file is still downloading', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'downloading', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    expect(row.queryByRole('button', { name: 'Fix Match' })).not.toBeInTheDocument()
  })

  test('clicking Fix Match opens the movie file-path modal, not the show-rematch modal', async () => {
    mockShowDetail(baseShow({ content_type: 'movie', media_type: 'movie' }), {
      files: [{ id: 5, original_filename: 'Movie.2020.mkv', status: 'matched', show_id: 1 }],
    })
    render(createElement(ShowDetail), { wrapper: makeWrapper() })

    const filenameEl = await screen.findByText('Movie.2020.mkv')
    const row = within(filenameEl.parentElement as HTMLElement)
    fireEvent.click(row.getByRole('button', { name: 'Fix Match' }))

    // The replace-mode ScanLocalMovieFileModal — lets the user type a path
    // directly or pick from a scan of the local path — not RematchModal
    // (which reassigns the file to a different show/movie entirely).
    expect(await screen.findByText('Fix movie file')).toBeInTheDocument()
    expect(screen.getByLabelText('Enter the file path directly')).toBeInTheDocument()
    expect(screen.queryByText('Fix show assignment')).not.toBeInTheDocument()

    const scanCall = vi
      .mocked(fetch)
      .mock.calls.find(([input]) => String(input).includes('/scan-local-movie-file'))
    expect(String(scanCall?.[0])).toContain('replace=true')
  })
})
