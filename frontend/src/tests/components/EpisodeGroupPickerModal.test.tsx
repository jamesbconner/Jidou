import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { EpisodeGroupPickerModal } from '@/components/EpisodeGroupPickerModal'
import type { ShowRead, EpisodeGroupSummary } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
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

const show: ShowRead = {
  id: 1,
  tmdb_id: 100,
  title: 'Test Show',
  media_type: 'tv',
  poster_path: null,
  backdrop_path: null,
  vote_count: 0,
  cached: false,
  list_poster_path: null,
  detail_poster_path: null,
  active_episode_group_id: 'group-b',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as ShowRead

const groups: EpisodeGroupSummary[] = [
  {
    id: 'group-a',
    name: 'Native Order',
    type: 1,
    episode_count: 24,
    group_count: 1,
    is_active: false,
  },
  {
    id: 'group-b',
    name: 'US Broadcast Order',
    type: 6,
    episode_count: 12,
    group_count: 1,
    is_active: true,
  },
]

describe('EpisodeGroupPickerModal', () => {
  test('renders each group with its episode/group counts', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(groups))
    render(<EpisodeGroupPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('US Broadcast Order')).toBeInTheDocument())
    expect(screen.getByText('Native Order')).toBeInTheDocument()
    expect(screen.getByText('24 episodes · 1 group')).toBeInTheDocument()
    expect(screen.getByText('12 episodes · 1 group')).toBeInTheDocument()
  })

  test('shows empty state when no alternate groupings are available', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse([]))
    render(<EpisodeGroupPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() =>
      expect(
        screen.getByText('No alternate episode groupings available for this show on TMDB.'),
      ).toBeInTheDocument(),
    )
  })

  test('marks the active group and disables its Apply button', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(groups))
    render(<EpisodeGroupPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Active')).toBeInTheDocument())
    expect(screen.getByText('Active')).toBeDisabled()
    expect(screen.getByText('Apply')).not.toBeDisabled()
  })

  test('picking a different group confirms before applying, then POSTs', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(mockResponse(groups))
      .mockResolvedValueOnce(
        mockResponse({
          episodes: [],
          episodes_added: 12,
          episodes_removed: 24,
          orphaned_file_count: 3,
          orphaned_watched_count: 1,
        }),
      )
    render(<EpisodeGroupPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Apply')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Apply'))
    expect(screen.getByText('Apply alternate episode grouping?')).toBeInTheDocument()

    const confirmButtons = screen.getAllByRole('button', { name: 'Apply' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])

    await waitFor(() => {
      const postCall = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      expect(postCall![0]).toBe('/api/shows/1/episode-groups/group-a/apply')
    })
    await waitFor(() =>
      expect(
        screen.getByText(
          /Applied: 12 episodes added, 24 removed, 3 files need rescanning, 1 watched episode lost watch history/,
        ),
      ).toBeInTheDocument(),
    )
  })

  test('close button triggers onClose', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(groups))
    const onClose = vi.fn()
    render(<EpisodeGroupPickerModal show={show} onClose={onClose} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
