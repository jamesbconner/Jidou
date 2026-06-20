import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Watchlist from '@/pages/Watchlist'
import type { WatchlistList } from '@/types/api'

const entries: WatchlistList[] = [
  { id: 1, show_id: 10, status: 'watching', position: 0, created_at: '2026-06-01T00:00:00Z' },
  { id: 2, show_id: 20, status: 'planned', position: 1, created_at: '2026-06-02T00:00:00Z' },
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
      expect(screen.getByText('No watchlist entries. Add a show above.')).toBeInTheDocument(),
    )
  })

  test('renders table rows for each entry', async () => {
    mockList(entries)
    render(<Watchlist />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('10')).toBeInTheDocument())
    expect(screen.getByText('20')).toBeInTheDocument()
    // 'Watching' and 'Planned' appear in both filter select and table status buttons
    expect(screen.getAllByText('Watching').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Planned').length).toBeGreaterThanOrEqual(1)
  })

  test('status filter select is present with All statuses default', async () => {
    mockList([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const select = screen.getAllByRole('combobox')[0]
    expect(select).toHaveValue('')
  })

  test('Add button is disabled when show_id input is empty', async () => {
    mockList([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const addButton = screen.getByRole('button', { name: 'Add' })
    expect(addButton).toBeDisabled()
  })

  test('Add button enables when show_id is entered', async () => {
    mockList([])
    render(<Watchlist />, { wrapper: makeWrapper() })
    const input = screen.getByPlaceholderText('e.g. 42')
    fireEvent.change(input, { target: { value: '5' } })
    expect(screen.getByRole('button', { name: 'Add' })).not.toBeDisabled()
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
