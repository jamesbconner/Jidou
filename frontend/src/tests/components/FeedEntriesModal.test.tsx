import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { FeedEntriesModal, groupStatus, spanLabel } from '@/components/FeedEntriesModal'
import type { FeedEntriesRead, FeedEntryGroupRead, RssFeedRead } from '@/types/api'

// See Watchlist.test.tsx for why fetch is a plain assignment rather than
// vi.spyOn, and why Response is duck-typed rather than constructed for real.
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

const feed = {
  id: 7,
  remote_key: '0',
  name: 'Example Tracker',
  url: 'https://tracker.example/rss',
  active: true,
} as RssFeedRead

function group(overrides: Partial<FeedEntryGroupRead> = {}): FeedEntryGroupRead {
  return {
    parsed_name: 'Brand New Show',
    entry_count: 2,
    season_min: 1,
    season_max: 1,
    episode_min: 3,
    episode_max: 4,
    sample_titles: ['Brand.New.Show.S01E03.1080p', 'Brand.New.Show.S01E04.1080p'],
    library_show: null,
    existing_subscription_id: null,
    ...overrides,
  }
}

function entries(groups: FeedEntryGroupRead[], extra: Partial<FeedEntriesRead> = {}): FeedEntriesRead {
  return {
    feed_id: 7,
    total_entries: groups.reduce((n, g) => n + g.entry_count, 0),
    truncated: false,
    malformed: false,
    cached: false,
    groups,
    ...extra,
  }
}

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <FeedEntriesModal feed={feed} onClose={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('groupStatus / spanLabel', () => {
  test('status precedence: subscribed > in library > new', () => {
    expect(groupStatus(group())).toBe('new')
    expect(
      groupStatus(group({ library_show: { id: 1, title: 'X', status: null, poster_path: null } })),
    ).toBe('in_library')
    expect(
      groupStatus(
        group({
          library_show: { id: 1, title: 'X', status: null, poster_path: null },
          existing_subscription_id: 5,
        }),
      ),
    ).toBe('subscribed')
  })

  test.each([
    [{ season_min: 2, season_max: 2, episode_min: 5, episode_max: 5 }, 'S02 E05'],
    [{ season_min: 1, season_max: 2, episode_min: 5, episode_max: 12 }, 'S01–S02 E05–E12'],
    [{ season_min: null, season_max: null, episode_min: 7, episode_max: 9 }, 'E07–E09'],
    [{ season_min: null, season_max: null, episode_min: null, episode_max: null }, ''],
  ])('spanLabel %j -> %s', (span, expected) => {
    expect(spanLabel(group(span))).toBe(expected)
  })
})

describe('FeedEntriesModal', () => {
  test('fetches the feed entries and renders groups with status badges and samples', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(
        entries([
          group(),
          group({
            parsed_name: 'Known Show',
            library_show: { id: 42, title: 'Known Show', status: null, poster_path: null },
          }),
        ]),
      ),
    )

    renderModal()

    expect(await screen.findByText('Brand New Show')).toBeInTheDocument()
    expect(screen.getByText('New')).toBeInTheDocument()
    expect(screen.getByText('In library')).toBeInTheDocument()
    expect(screen.getAllByText('Brand.New.Show.S01E03.1080p').length).toBeGreaterThan(0)
    expect(screen.getAllByText(/S01 E03–E04/).length).toBeGreaterThan(0)
    expect(vi.mocked(globalThis.fetch).mock.calls[0][0]).toBe('/api/rss/feeds/7/entries')
    const link = screen.getAllByRole('link').find((a) => a.getAttribute('href') === '/shows/42')
    expect(link).toBeDefined()
  })

  test('hides subscribed groups by default and shows them under the Subscribed filter', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(
        entries([
          group(),
          group({
            parsed_name: 'Already Subscribed',
            library_show: { id: 9, title: 'Already Subscribed', status: null, poster_path: null },
            existing_subscription_id: 3,
          }),
        ]),
      ),
    )

    renderModal()
    await screen.findByText('Brand New Show')

    expect(screen.queryByText('Already Subscribed')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('radio', { name: 'Subscribed' }))

    expect(screen.getByText('Already Subscribed')).toBeInTheDocument()
    expect(screen.queryByText('Brand New Show')).not.toBeInTheDocument()
  })

  test('shows the backend error detail when the fetch fails', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse({ detail: 'Feed server returned HTTP 403' }, 502),
    )

    renderModal()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Feed server returned HTTP 403')
  })

  test('warns when the feed XML was malformed or truncated', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(entries([group()], { malformed: true, truncated: true })),
    )

    renderModal()

    expect(await screen.findByText(/feed XML is malformed/)).toBeInTheDocument()
    expect(screen.getByText(/only the first 2 are listed/)).toBeInTheDocument()
  })

  test('labels unparsed titles instead of hiding them', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(entries([group({ parsed_name: null, sample_titles: ['[1080p]'] })])),
    )

    renderModal()

    expect(await screen.findByText('Unrecognized titles')).toBeInTheDocument()
  })

  test('Refresh refetches with refresh=true and replaces the displayed groups', async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(mockResponse(entries([group()], { cached: true })))
      .mockResolvedValueOnce(mockResponse(entries([group({ parsed_name: 'Fresh Show' })])))

    renderModal()
    await screen.findByText('Brand New Show')
    expect(screen.getByText('Cached result')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))

    expect(await screen.findByText('Fresh Show')).toBeInTheDocument()
    await waitFor(() => {
      expect(vi.mocked(globalThis.fetch).mock.calls[1][0]).toBe('/api/rss/feeds/7/entries?refresh=true')
    })
    expect(screen.queryByText('Cached result')).not.toBeInTheDocument()
  })

  test('says so when the feed has no entries', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockResponse(entries([])))

    renderModal()

    expect(await screen.findByText('This feed has no entries.')).toBeInTheDocument()
  })
})

describe('FeedEntriesModal add action', () => {
  test('offers Add only for new and in-library groups with a parsed name', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse([]))
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(
        entries([
          group({ parsed_name: 'Brand New Show' }),
          group({
            parsed_name: 'Known Show',
            library_show: { id: 42, title: 'Known Show', status: null, poster_path: null },
          }),
          group({
            parsed_name: 'Already Subscribed',
            library_show: { id: 9, title: 'Already Subscribed', status: null, poster_path: null },
            existing_subscription_id: 3,
          }),
          group({ parsed_name: null, sample_titles: ['[1080p]'] }),
        ]),
      ),
    )

    renderModal()
    await screen.findByText('Brand New Show')
    fireEvent.click(screen.getByRole('radio', { name: 'All' }))

    // New + In library get an action; Subscribed and Unrecognized do not.
    expect(screen.getAllByRole('button', { name: /^Add/ })).toHaveLength(2)
  })

  test('Add opens the pane for that group and hides the button', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(mockResponse([]))
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse(entries([group({ parsed_name: 'Brand New Show' })])),
    )

    renderModal()
    await screen.findByText('Brand New Show')

    fireEvent.click(screen.getByRole('button', { name: /^Add/ }))

    expect(screen.getByLabelText('Search for the show')).toHaveValue('Brand New Show')
    expect(screen.queryByRole('button', { name: 'Add…' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByLabelText('Search for the show')).not.toBeInTheDocument()
  })
})


describe('FeedEntriesModal after a successful add', () => {
  test('keeps the added group and its outcome on screen despite the default filter', async () => {
    let subscribed = false
    const route = (url: string, init?: RequestInit): Response => {
      if (url.includes('/add-show')) {
        subscribed = true
        return mockResponse({
          show: { id: 42, title: 'Brand New Show', status: null, poster_path: null },
          show_created: true,
          subscription: null,
          subscription_created: true,
          adopted_stub: false,
          alias_added: false,
          dry_run: false,
        })
      }
      if (url.includes('/suggest-regex')) {
        return mockResponse({
          regex_include: 'Brand.New.Show',
          regex_exclude: '',
          model: 'm',
          cached: false,
          match: { matched_titles: [], unmatched_titles: [], total: 0 },
        })
      }
      if (url.includes('/shows/tmdb/search')) {
        return mockResponse({
          results: [
            {
              id: 555,
              name: 'Brand New Show',
              media_type: 'tv',
              overview: '',
              poster_path: null,
              backdrop_path: null,
              vote_average: 1,
              vote_count: 1,
              original_language: 'en',
            },
          ],
          total_results: 1,
          total_pages: 1,
          page: 1,
        })
      }
      if (url.includes('/entries')) {
        // After the add, the server reports the group as subscribed.
        return mockResponse(
          entries([
            group({
              parsed_name: 'Brand New Show',
              library_show: subscribed
                ? { id: 42, title: 'Brand New Show', status: null, poster_path: null }
                : null,
              existing_subscription_id: subscribed ? 5 : null,
            }),
          ]),
        )
      }
      void init
      return mockResponse([])
    }
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      route(String(input), init),
    ) as typeof fetch

    renderModal()
    await screen.findByText('Brand New Show')
    fireEvent.click(screen.getByRole('button', { name: /^Add/ }))
    fireEvent.click(await screen.findByRole('option', { name: /Brand New Show.*TMDB/ }))
    await waitFor(() =>
      expect(screen.getByLabelText('Include regex')).toHaveValue('Brand.New.Show'),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Add show + subscription' }))

    // The refetch makes the group "Subscribed"; its outcome must still be readable.
    expect(await screen.findByRole('status')).toHaveTextContent(/Added “Brand New Show”/)
    // 'Subscribed' is both the filter button and the row's badge once it flips.
    await waitFor(() => expect(screen.getAllByText('Subscribed').length).toBeGreaterThanOrEqual(2))
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open show' })).toHaveAttribute('href', '/shows/42')
  })
})

