import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { PosterPickerModal } from '@/components/PosterPickerModal'
import type { ShowRead, PosterOption } from '@/types/api'

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
  poster_path: '/default.jpg',
  backdrop_path: null,
  vote_count: 0,
  cached: false,
  list_poster_path: null,
  detail_poster_path: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as ShowRead

const posters: PosterOption[] = [
  { file_path: '/default.jpg', width: 500, height: 750, vote_average: 8, iso_639_1: 'en' },
  { file_path: '/alt.jpg', width: 500, height: 750, vote_average: 5, iso_639_1: null },
]

describe('PosterPickerModal', () => {
  test('renders each poster with its thumbnail', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(posters))
    render(<PosterPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getAllByRole('img')).toHaveLength(2))
    expect(screen.getAllByRole('img', { name: /poster option/ })).toHaveLength(2)
  })

  test('shows empty state when no posters are available', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse([]))
    render(<PosterPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() =>
      expect(screen.getByText('No alternate posters available for this show.')).toBeInTheDocument(),
    )
  })

  test('marks the poster matching poster_path as active for both targets by default', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(posters))
    render(<PosterPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getAllByRole('img')).toHaveLength(2))
    expect(screen.getByText('Shows page')).toBeInTheDocument()
    expect(screen.getByText('Details page')).toBeInTheDocument()
  })

  test('clicking "Use for Shows" PATCHes list_poster_path', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(mockResponse(posters))
      .mockResolvedValueOnce(mockResponse({ ...show, list_poster_path: '/alt.jpg' }))
    render(<PosterPickerModal show={show} onClose={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getAllByRole('img')).toHaveLength(2))

    const useForShowsButtons = screen.getAllByText('Use for Shows')
    fireEvent.click(useForShowsButtons[1]) // the /alt.jpg card

    await waitFor(() => {
      const patchCall = vi
        .mocked(fetch)
        .mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === 'PATCH')
      expect(patchCall).toBeDefined()
      expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual({
        list_poster_path: '/alt.jpg',
      })
    })
  })

  test('close button triggers onClose', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse(posters))
    const onClose = vi.fn()
    render(<PosterPickerModal show={show} onClose={onClose} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByLabelText('Close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
