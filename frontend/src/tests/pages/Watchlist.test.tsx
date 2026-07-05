import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Watchlist from '@/pages/Watchlist'
import type { WatchlistList } from '@/types/api'

const entries: WatchlistList[] = [
  { id: 1, show_id: 10, show: { title: 'Show Alpha', tmdb_id: 110, poster_path: null }, status: 'watching', position: 0, created_at: '2026-06-01T00:00:00Z' },
  { id: 2, show_id: 20, show: { title: 'Show Beta', tmdb_id: 120, poster_path: null }, status: 'planned', position: 1, created_at: '2026-06-02T00:00:00Z' },
]

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      MemoryRouter,
      {},
      createElement(QueryClientProvider, { client: qc }, children),
    )
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735) — property-descriptor
// manipulation on the native fetch/undici binding is implicated. A plain
// assignment achieves the same mockability without touching the native
// descriptor, and is restored explicitly since test files now share one
// global context (see vitest.config.ts isolate: false).
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

// Duck-types the subset of the Fetch Response interface api/client.ts
// actually reads (.ok, .status, .json()) instead of constructing a real
// Response — the native/undici Response implementation triggers a worker
// crash on Node >=22.1.x (https://github.com/nodejs/node/issues/54735).
function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

function mockWatchlistAndShows(watchlistData: WatchlistList[]) {
  vi.mocked(fetch).mockResolvedValue(mockResponse(watchlistData))
}

describe('Watchlist page', () => {
  test('renders heading and empty state when no entries', async () => {
    mockWatchlistAndShows([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    expect(screen.getByText('Watchlist')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('No watchlist entries yet.')).toBeInTheDocument(),
    )
  })

  test('renders table rows with show name and TMDB ID', async () => {
    mockWatchlistAndShows(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Show Alpha')).toBeInTheDocument())
    expect(screen.getByText('Show Beta')).toBeInTheDocument()
    expect(screen.getByText('TMDB #110')).toBeInTheDocument()
    expect(screen.getByText('TMDB #120')).toBeInTheDocument()
    expect(screen.getAllByText('Watching').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Planned').length).toBeGreaterThanOrEqual(1)
  })

  test('show name links to show detail page', async () => {
    mockWatchlistAndShows(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Show Alpha')).toBeInTheDocument())
    const link = screen.getByText('Show Alpha').closest('a')
    expect(link).toHaveAttribute('href', '/shows/10')
  })

  test('status filter select is present with All statuses default', async () => {
    mockWatchlistAndShows([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const select = screen.getAllByRole('combobox')[0]
    expect(select).toHaveValue('')
  })

  test('search input and Library/TMDB toggle are present', async () => {
    mockWatchlistAndShows([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    expect(screen.getByPlaceholderText('Search your library…')).toBeInTheDocument()
    expect(screen.getByRole('switch')).toBeInTheDocument()
  })

  test('toggle switches between Library and TMDB mode', async () => {
    mockWatchlistAndShows([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const toggle = screen.getByRole('switch')
    expect(toggle).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByPlaceholderText('Search TMDB…')).toBeInTheDocument()
  })

  test('renders drag handle cells for each row', async () => {
    mockWatchlistAndShows(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Show Alpha')).toBeInTheDocument())
    const handles = document.querySelectorAll('td[title="Drag to reorder"]')
    expect(handles).toHaveLength(2)
  })

  test('Remove button calls DELETE endpoint', async () => {
    mockWatchlistAndShows(entries)
    vi.mocked(fetch)
      .mockResolvedValueOnce(mockResponse(entries))
      .mockResolvedValueOnce(mockResponse(null, 204))

    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getAllByText('Remove')).toHaveLength(2))

    fireEvent.click(screen.getAllByText('Remove')[0])
    await waitFor(() => {
      const deleteCalls = vi.mocked(fetch).mock.calls.filter(
        (c) => (c[1] as RequestInit | undefined)?.method === 'DELETE',
      )
      expect(deleteCalls).toHaveLength(1)
    })
  })
})
