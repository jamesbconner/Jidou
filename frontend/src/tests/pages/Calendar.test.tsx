import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Calendar from '@/pages/Calendar'
import { addDays, toISODate } from '@/utils/calendarRange'
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
    track_missing_episodes: true,
    has_active_rss_subscription: true,
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
    track_missing_episodes: true,
    has_active_rss_subscription: true,
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

// Routes the sync-missing POST to its own response, distinct from every
// other GET (all of which resolve `data`) -- api.post always sends the URL
// as a plain string, so a substring check is enough to dispatch on it.
function mockCalendarAndSync(
  data: CalendarEpisode[],
  syncResponse: { body: unknown; status?: number },
) {
  vi.mocked(fetch).mockImplementation((input) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    if (url.includes('/shows/calendar/sync-missing')) {
      return Promise.resolve(mockResponse(syncResponse.body, syncResponse.status ?? 200))
    }
    return Promise.resolve(mockResponse(data))
  })
}

function todayDate(): Date {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d
}

function rangeParagraph(): HTMLElement {
  return screen.getByText((_, element) => {
    if (!element || element.tagName !== 'P') return false
    return /–/.test(element.textContent ?? '')
  })
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

describe('Calendar page range/anchor settings', () => {
  test('defaults reproduce the original 7-day, Monday-start behavior', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    expect(screen.getByRole('radio', { name: '7' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Week start' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Mon' })).toBeChecked()
  })

  test('selecting a shorter range narrows the date span and falls back the anchor', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('radio', { name: '3' }))

    expect(screen.getByRole('radio', { name: 'Today start' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Week start' })).not.toBeChecked()

    const today = todayDate()
    const expected = `${toISODate(today)} – ${toISODate(addDays(today, 2))}`
    expect(rangeParagraph().textContent).toContain(expected)
  })

  test('selecting the centered anchor centers today in the range', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('radio', { name: 'Centered' }))

    const today = todayDate()
    const expected = `${toISODate(addDays(today, -3))} – ${toISODate(addDays(today, 3))}`
    expect(rangeParagraph().textContent).toContain(expected)
  })

  test('the week-start anchor option is disabled unless range length is 7', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('radio', { name: '3' }))
    expect(screen.getByRole('radio', { name: 'Week start' })).toBeDisabled()

    fireEvent.click(screen.getByRole('radio', { name: '7' }))
    expect(screen.getByRole('radio', { name: 'Week start' })).not.toBeDisabled()
  })

  test('the "Week begins" control only shows for the week-start anchor', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    expect(screen.getByRole('radio', { name: 'Mon' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: 'Today start' }))
    expect(screen.queryByRole('radio', { name: 'Mon' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: 'Week start' }))
    expect(screen.getByRole('radio', { name: 'Mon' })).toBeInTheDocument()
  })

  test('range settings persist to localStorage independently of filters and are restored on remount', async () => {
    mockCalendar(episodes)
    const { unmount } = render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('radio', { name: 'Sun' }))

    const stored = JSON.parse(window.localStorage.getItem('jidou:calendar-range') ?? '{}')
    expect(stored).toEqual({ rangeLength: 7, anchorMode: 'week-start', weekStartDay: 'sunday' })
    expect(window.localStorage.getItem('jidou:calendar-filters')).toBeNull()

    unmount()
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())
    expect(screen.getByRole('radio', { name: 'Sun' })).toBeChecked()
  })

  test('changing a setting after paging resets to a fresh today-anchored window', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const initialRange = rangeParagraph().textContent

    fireEvent.click(screen.getByText('Next →'))
    expect(rangeParagraph().textContent).not.toBe(initialRange)

    fireEvent.click(screen.getByRole('radio', { name: '3' }))

    const today = todayDate()
    const expected = `${toISODate(today)} – ${toISODate(addDays(today, 2))}`
    expect(rangeParagraph().textContent).toContain(expected)
  })
})

describe('Calendar page sync-missing button', () => {
  test('disabled with no count when no episode in view is missing', async () => {
    mockCalendar(episodes.map((ep) => ({ ...ep, status: 'tracked' })))
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const button = screen.getByRole('button', { name: 'Sync missing' })
    expect(button).toBeDisabled()
  })

  test('enabled with the distinct missing-show count when episodes are missing', async () => {
    mockCalendar(episodes) // fixture already has one 'missing' episode (The Wire)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const button = screen.getByRole('button', { name: 'Sync missing (1)' })
    expect(button).not.toBeDisabled()
  })

  test('excludes missing episodes from shows opted out of missing-episode tracking', async () => {
    // Regression test: a show the user explicitly toggled to "Ignore Missing
    // Eps" has track_missing_episodes=False, and shouldn't inflate the "Sync
    // missing" count or be a candidate for the sync it triggers.
    mockCalendar(episodes.map((ep) => ({ ...ep, track_missing_episodes: false })))
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const button = screen.getByRole('button', { name: 'Sync missing' })
    expect(button).toBeDisabled()
  })

  test('excludes missing episodes from shows with no active RSS subscription', async () => {
    // Regression test: a show with no RSS feed configured at all will never
    // auto-download its episodes, so it shouldn't inflate the "Sync missing"
    // count or be a candidate for the sync it triggers -- even if the user
    // never explicitly toggled "Ignore Missing Eps" for it.
    mockCalendar(episodes.map((ep) => ({ ...ep, has_active_rss_subscription: false })))
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const button = screen.getByRole('button', { name: 'Sync missing' })
    expect(button).toBeDisabled()
  })

  test('shows a criteria explanation next to the button', async () => {
    mockCalendar(episodes)
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    const info = screen.getByRole('button', {
      name: 'What counts as a missing show for Sync missing',
    })
    expect(info).toHaveAttribute('title', expect.stringContaining('active RSS subscription'))
  })

  test('clicking syncs and reports the aggregated result', async () => {
    mockCalendarAndSync(episodes, {
      body: { shows_synced: 1, shows_failed: 0, episodes_upserted: 2 },
    })
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Sync missing (1)' }))

    await waitFor(() =>
      expect(screen.getByText('Synced 1 show · 2 episodes updated.')).toBeInTheDocument(),
    )
  })

  test('reports partial failure when some shows fail to sync', async () => {
    mockCalendarAndSync(episodes, {
      body: { shows_synced: 1, shows_failed: 1, episodes_upserted: 2 },
    })
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Sync missing (1)' }))

    await waitFor(() =>
      expect(
        screen.getByText('Synced 1 show · 2 episodes updated · 1 failed.'),
      ).toBeInTheDocument(),
    )
  })

  test('shows an error message when the sync request fails', async () => {
    mockCalendarAndSync(episodes, { body: { detail: 'TMDB unavailable' }, status: 502 })
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Sync missing (1)' }))

    await waitFor(() =>
      expect(screen.getByText('Sync failed: TMDB unavailable.')).toBeInTheDocument(),
    )
  })

  test('the success banner clears once the viewed range changes', async () => {
    mockCalendarAndSync(episodes, {
      body: { shows_synced: 1, shows_failed: 0, episodes_upserted: 2 },
    })
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Sync missing (1)' }))
    await waitFor(() =>
      expect(screen.getByText('Synced 1 show · 2 episodes updated.')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByText('Next →'))

    await waitFor(() =>
      expect(screen.queryByText('Synced 1 show · 2 episodes updated.')).not.toBeInTheDocument(),
    )
  })

  test('a later failed sync clears the previous success banner, not just adds to it', async () => {
    let syncCallCount = 0
    vi.mocked(fetch).mockImplementation((input) => {
      const url = typeof input === 'string' ? input : (input as Request).url
      if (url.includes('/shows/calendar/sync-missing')) {
        syncCallCount += 1
        return Promise.resolve(
          syncCallCount === 1
            ? mockResponse({ shows_synced: 1, shows_failed: 0, episodes_upserted: 2 })
            : mockResponse({ detail: 'TMDB unavailable' }, 502),
        )
      }
      return Promise.resolve(mockResponse(episodes))
    })
    render(<Calendar />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Attack on Titan')).toBeInTheDocument())
    const button = () => screen.getByRole('button', { name: 'Sync missing (1)' })

    fireEvent.click(button())
    await waitFor(() =>
      expect(screen.getByText('Synced 1 show · 2 episodes updated.')).toBeInTheDocument(),
    )

    fireEvent.click(button())

    await waitFor(() =>
      expect(screen.getByText('Sync failed: TMDB unavailable.')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Synced 1 show · 2 episodes updated.')).not.toBeInTheDocument()
  })
})
