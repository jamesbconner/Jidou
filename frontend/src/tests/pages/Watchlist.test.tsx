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

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch')
})

afterEach(() => {
  vi.restoreAllMocks()
})

function mockList(data: WatchlistList[]) {
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }),
  )
}

describe('Watchlist page', () => {
  test('renders heading and empty state when no entries', async () => {
    mockList([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    expect(screen.getByText('Watchlist')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('No watchlist entries yet.')).toBeInTheDocument(),
    )
  })

  test('renders table rows with show name and TMDB ID', async () => {
    mockList(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Show Alpha')).toBeInTheDocument())
    expect(screen.getByText('Show Beta')).toBeInTheDocument()
    expect(screen.getByText('TMDB #110')).toBeInTheDocument()
    expect(screen.getByText('TMDB #120')).toBeInTheDocument()
    // Status badges
    expect(screen.getAllByText('Watching').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Planned').length).toBeGreaterThanOrEqual(1)
  })

  test('show name links to show detail page', async () => {
    mockList(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Show Alpha')).toBeInTheDocument())
    const link = screen.getByText('Show Alpha').closest('a')
    expect(link).toHaveAttribute('href', '/shows/10')
  })

  test('status filter select is present with All statuses default', async () => {
    mockList([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const select = screen.getAllByRole('combobox')[0]
    expect(select).toHaveValue('')
  })

  test('Remove button calls DELETE endpoint', async () => {
    mockList(entries)
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(entries), { status: 200, headers: { 'Content-Type': 'application/json' } }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))

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
