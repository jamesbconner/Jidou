import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Shows from '@/pages/Shows'
import type { ShowList } from '@/types/api'

// Deliberately avoids tripping any of DQ_CHECKS (no_path/no_content_type/
// no_local_episodes/orphan) — otherwise the same show would also appear in
// the pre-existing "Issue table" below, colliding with getByText assertions
// aimed only at the new Missing Episodes aggregation table.
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

function mockShowsPage(shows: ShowList[]) {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const url = String(input)
    if (url.startsWith('/api/shows?')) return mockResponse(shows)
    return mockResponse([])
  })
}

async function openDataQualityTab() {
  render(<Shows />, { wrapper: makeWrapper() })
  await waitFor(() => expect(screen.getByText(/Data Quality/)).toBeInTheDocument())
  fireEvent.click(screen.getByText(/Data Quality/))
}

describe('Shows page — Missing Episodes aggregation', () => {
  test('shows an empty state when no shows have missing episodes', async () => {
    mockShowsPage([makeShow({ missing_episode_count: 0 })])
    await openDataQualityTab()
    await waitFor(() =>
      expect(screen.getByText('No missing episodes across the library.')).toBeInTheDocument(),
    )
  })

  test('lists shows with missing episodes, sorted by count descending', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Low Gaps', missing_episode_count: 2 }),
      makeShow({ id: 2, title: 'High Gaps', missing_episode_count: 40 }),
    ])
    await openDataQualityTab()
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
    await openDataQualityTab()
    await waitFor(() => expect(screen.getByText('Gappy Show')).toBeInTheDocument())
    expect(screen.queryByText('Complete Show')).not.toBeInTheDocument()
  })

  test('filters the list by title', async () => {
    mockShowsPage([
      makeShow({ id: 1, title: 'Breaking Bad', missing_episode_count: 3 }),
      makeShow({ id: 2, title: 'Better Call Saul', missing_episode_count: 5 }),
    ])
    await openDataQualityTab()
    await waitFor(() => expect(screen.getByText('Breaking Bad')).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText('Filter by title…'), {
      target: { value: 'saul' },
    })
    expect(screen.queryByText('Breaking Bad')).not.toBeInTheDocument()
    expect(screen.getByText('Better Call Saul')).toBeInTheDocument()
  })

  test('show title links to show detail page', async () => {
    mockShowsPage([makeShow({ id: 42, title: 'Linked Show', missing_episode_count: 1 })])
    await openDataQualityTab()
    await waitFor(() => expect(screen.getByText('Linked Show')).toBeInTheDocument())
    expect(screen.getByText('Linked Show').closest('a')).toHaveAttribute('href', '/shows/42')
  })
})
