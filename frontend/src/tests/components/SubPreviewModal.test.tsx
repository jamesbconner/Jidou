import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { SubPreviewModal } from '@/components/SubPreviewModal'
import type { RssSubscriptionRead } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

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

const sub: RssSubscriptionRead = {
  id: 7,
  remote_key: '3',
  feed_id: 1,
  show_id: null,
  name: 'My Show',
  regex_include: null,
  regex_exclude: null,
  regex_include_ignorecase: true,
  regex_exclude_ignorecase: true,
  download_location: null,
  move_completed: null,
  active: true,
  enabled_in_config: true,
  label: null,
  last_match: null,
  extra_config: null,
  feed: null,
  show: null,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

describe('SubPreviewModal', () => {
  test('fetches and renders the composed preview from the backend', async () => {
    vi.mocked(fetch).mockResolvedValue(
      mockResponse({ key: '3', name: 'My Show', active: true, max_connections: 50 }),
    )

    render(createElement(SubPreviewModal, { sub, onClose: vi.fn() }), { wrapper: makeWrapper() })

    expect(screen.getByText(/Composed output for/)).toBeInTheDocument()
    expect(screen.getByText('My Show', { selector: 'strong' })).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.getByText(/"max_connections": 50/)).toBeInTheDocument()
    })

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toContain('/rss/subscriptions/7/preview')
  })

  test('shows an error message when the preview request fails', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ detail: 'not found' }, 404))

    render(createElement(SubPreviewModal, { sub, onClose: vi.fn() }), { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Failed to load preview.')).toBeInTheDocument()
    })
  })

  test('calls onClose when the Close button is clicked', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ key: '3' }))
    const onClose = vi.fn()

    render(createElement(SubPreviewModal, { sub, onClose }), { wrapper: makeWrapper() })

    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('shows "unassigned" when the subscription has no remote_key yet', () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ key: 'unassigned' }))
    const stub: RssSubscriptionRead = { ...sub, remote_key: null }

    render(createElement(SubPreviewModal, { sub: stub, onClose: vi.fn() }), {
      wrapper: makeWrapper(),
    })

    expect(screen.getByText(/key: unassigned/)).toBeInTheDocument()
  })
})
