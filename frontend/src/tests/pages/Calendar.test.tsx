import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Calendar from '@/pages/Calendar'
import type { CalendarEpisode } from '@/types/api'

function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const TODAY = todayIso()

const episodes: CalendarEpisode[] = [
  {
    episode_id: 1,
    show_id: 10,
    show_title: 'Attack on Titan',
    poster_path: null,
    season_number: 1,
    episode_number: 1,
    name: 'To You, in 2000 Years',
    air_date: TODAY,
    status: 'tracked',
    content_type: 'anime',
    genres: [{ id: 16, name: 'Animation' }],
  },
  {
    episode_id: 2,
    show_id: 20,
    show_title: 'The Wire',
    poster_path: null,
    season_number: 1,
    episode_number: 1,
    name: 'The Target',
    air_date: TODAY,
    status: 'missing',
    content_type: 'tv',
    genres: [{ id: 80, name: 'Crime' }],
  },
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

// See Watchlist.test.tsx for why fetch is mocked via plain assignment rather
// than vi.spyOn, and Response is duck-typed rather than constructed.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
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

function mockCalendar(data: CalendarEpisode[]) {
  vi.mocked(fetch).mockResolvedValue(mockResponse(data))
}

describe('Calendar page', () => {
  test('renders heading and episodes for the current week', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    expect(screen.getByText('Calendar')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())
    expect(screen.getByText('The Wire')).toBeInTheDocument()
  })

  test('filter bar shows search input and content type select', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    expect(screen.getByPlaceholderText('Search shows…')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())
  })

  test('content type filter narrows the visible episodes', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const typeSelect = screen.getAllByRole('combobox')[0]
    fireEvent.change(typeSelect, { target: { value: 'anime' } })

    await waitFor(() => expect(screen.queryByText('The Wire')).not.toBeInTheDocument())
    expect(screen.getByText('Attack on Titan')).toBeInTheDocument()
  })

  test('genre filter narrows the visible episodes', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const selects = screen.getAllByRole('combobox')
    const genreSelect = selects.find((s) =>
      Array.from((s as HTMLSelectElement).options).some((o) => o.value === 'Crime'),
    ) as HTMLSelectElement
    fireEvent.change(genreSelect, { target: { value: 'Crime' } })

    await waitFor(() => expect(screen.queryByText('Attack on Titan')).not.toBeInTheDocument())
    expect(screen.getByText('The Wire')).toBeInTheDocument()
  })

  test('search filters by substring match, not exact title', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText('Search shows…'), { target: { value: 'titan' } })

    await waitFor(() => expect(screen.queryByText('The Wire')).not.toBeInTheDocument(), {
      timeout: 2000,
    })
    expect(screen.getByText('Attack on Titan')).toBeInTheDocument()
  })

  test('Clear filters resets active filters and restores hidden episodes', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const typeSelect = screen.getAllByRole('combobox')[0]
    fireEvent.change(typeSelect, { target: { value: 'anime' } })
    await waitFor(() => expect(screen.queryByText('The Wire')).not.toBeInTheDocument())

    fireEvent.click(screen.getByText(/Clear filters/))

    await waitFor(() => expect(screen.getByText('The Wire')).toBeInTheDocument())
    expect(typeSelect).toHaveValue('')
  })

  test('filters persist to localStorage and are restored on remount', async () => {
    mockCalendar(episodes)
    const { unmount } = render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const typeSelect = screen.getAllByRole('combobox')[0]
    fireEvent.change(typeSelect, { target: { value: 'anime' } })
    await waitFor(() => expect(screen.queryByText('The Wire')).not.toBeInTheDocument())

    const stored = JSON.parse(window.localStorage.getItem('jidou:calendar-filters') ?? '{}')
    expect(stored.filterContentType).toBe('anime')

    unmount()
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())
    expect(screen.queryByText('The Wire')).not.toBeInTheDocument()
    expect(screen.getAllByRole('combobox')[0]).toHaveValue('anime')
  })
})
