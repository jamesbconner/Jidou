import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { FeedFormModal } from '@/components/FeedFormModal'
import type { RssFeedRead } from '@/types/api'

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735); plain assignment avoids it.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown, status = 200): Response {
  return { ok: status < 300, status, statusText: '', json: async () => body } as Response
}

type Sample = { sample_name: string; hint: string }

function feedWith(samples: Sample[]): RssFeedRead {
  return {
    id: 1,
    remote_key: null,
    name: 'Feed',
    url: 'https://example.com/feed',
    default_download_location: null,
    default_move_completed: null,
    active: true,
    regex_include_samples: samples,
    regex_exclude_hint: null,
    extra_config: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  } as RssFeedRead
}

function renderModal(feed: RssFeedRead) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(FeedFormModal, { feed, onClose: vi.fn() }),
    ),
  )
}

describe('FeedFormModal — regex include samples', () => {
  test('shows existing samples and an Add sample button until 3', () => {
    renderModal(feedWith([{ sample_name: 'A.S01E01', hint: '^A.*' }]))
    expect(screen.getAllByPlaceholderText(/sample name/i)).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: /add sample/i }))
    fireEvent.click(screen.getByRole('button', { name: /add sample/i }))
    expect(screen.getAllByPlaceholderText(/sample name/i)).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /add sample/i })).toBeNull()
  })

  test('removing a row drops it', () => {
    renderModal(
      feedWith([
        { sample_name: 'A', hint: 'a' },
        { sample_name: 'B', hint: 'b' },
      ]),
    )
    fireEvent.click(screen.getAllByRole('button', { name: /remove sample/i })[0])
    expect(screen.getAllByPlaceholderText(/sample name/i)).toHaveLength(1)
  })

  test('save sends samples and drops rows with a blank hint', async () => {
    const fetchMock = vi.mocked(globalThis.fetch)
    fetchMock.mockResolvedValue(mockResponse({}))
    renderModal(feedWith([{ sample_name: 'A', hint: 'a' }]))
    fireEvent.click(screen.getByRole('button', { name: /add sample/i })) // blank row
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)
    expect(body.regex_include_samples).toEqual([{ sample_name: 'A', hint: 'a' }])
  })
})
