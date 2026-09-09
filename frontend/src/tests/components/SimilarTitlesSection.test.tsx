import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { SimilarTitlesSection } from '@/components/SimilarTitlesSection'
import type { AppSettings, DiscoverResult, ShowList } from '@/types/api'

function makeAppSettings(overrides: Partial<AppSettings> = {}): AppSettings {
  return {
    show_adult_content: false,
    calendar_enabled: true,
    discover_enabled: true,
    recent_episodes_enabled: true,
    recent_movies_enabled: true,
    recent_episodes_prefer_posters: false,
    similar_titles_enabled: true,
    similar_titles_count: 12,
    similar_titles_include_external: true,
    ...overrides,
  }
}

function makeResult(overrides: Partial<DiscoverResult> = {}): DiscoverResult {
  return {
    id: 1,
    media_type: 'tv',
    name: 'Similar Show',
    title: null,
    overview: null,
    poster_path: '/p.jpg',
    backdrop_path: null,
    vote_average: 8,
    vote_count: 100,
    release_date: null,
    first_air_date: null,
    original_language: 'en',
    genre_ids: null,
    origin_country: null,
    adult: null,
    seeded_from: [],
    ...overrides,
  } as DiscoverResult
}

function makeLibraryShow(overrides: Partial<ShowList> = {}): ShowList {
  return {
    id: 42,
    tmdb_id: 999,
    title: 'Owned Show',
    media_type: 'tv',
    ...overrides,
  } as ShowList
}

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

function setupFetch(options: {
  appSettings?: AppSettings
  similar?: DiscoverResult[]
  library?: ShowList[]
} = {}) {
  const appSettings = options.appSettings ?? makeAppSettings()
  const similar = options.similar ?? [makeResult()]
  const library = options.library ?? []

  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/settings')) return mockResponse(appSettings)
    if (url.includes('/api/shows/1/similar')) return mockResponse(similar)
    if (url.includes('/api/shows?')) return mockResponse(library)
    return mockResponse([])
  })
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(MemoryRouter, null, createElement(SimilarTitlesSection, { showId: 1 })),
    ),
  )
}

describe('SimilarTitlesSection', () => {
  test('renders a heading and one card per similar title', async () => {
    setupFetch({ similar: [makeResult({ id: 1, name: 'Show A' }), makeResult({ id: 2, name: 'Show B' })] })
    renderSection()

    expect(await screen.findByRole('heading', { name: 'Similar Titles' })).toBeInTheDocument()
    expect(await screen.findByText('Show A')).toBeInTheDocument()
    expect(screen.getByText('Show B')).toBeInTheDocument()
  })

  test('renders nothing and does not fetch /similar when the feature is disabled', async () => {
    setupFetch({ appSettings: makeAppSettings({ similar_titles_enabled: false }) })
    renderSection()

    // The ungated library query still fires; once it has, settings have
    // resolved too, so /similar would have been requested by now if it were
    // ever going to be.
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes('/api/shows?'))).toBe(
        true,
      ),
    )
    expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes('/similar'))).toBe(false)
    expect(screen.queryByRole('heading', { name: 'Similar Titles' })).not.toBeInTheDocument()
  })

  test('renders nothing when there are no matches', async () => {
    setupFetch({ similar: [] })
    renderSection()

    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes('/similar'))).toBe(true),
    )
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: 'Similar Titles' })).not.toBeInTheDocument(),
    )
  })

  test('an in-library match links to its detail page instead of offering Add', async () => {
    setupFetch({
      similar: [makeResult({ id: 999, media_type: 'tv', name: 'Owned Show' })],
      library: [makeLibraryShow({ id: 42, tmdb_id: 999, media_type: 'tv' })],
    })
    renderSection()

    const link = await screen.findByRole('link', { name: /view in library/i })
    expect(link).toHaveAttribute('href', '/shows/42')
    expect(screen.queryByRole('button', { name: /add \+ watchlist/i })).not.toBeInTheDocument()
  })

  test('a not-in-library match offers an Add + Watchlist action', async () => {
    setupFetch({ similar: [makeResult({ id: 7, name: 'Unowned Show' })], library: [] })
    renderSection()

    expect(
      await screen.findByRole('button', { name: /add \+ watchlist/i }),
    ).toBeInTheDocument()
  })
})
