import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { AssignImportModal } from '@/components/AssignImportModal'
import type { EpisodeList } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

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
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 422 ? 'Unprocessable Entity' : '',
    json: async () => body,
  } as Response
}

function episode(over: Partial<EpisodeList>): EpisodeList {
  return {
    id: 10,
    show_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Episode',
    file_tracked: false,
    watched: false,
    backing_files: [],
    tracked_filename_display: null,
    ...over,
  }
}

describe('AssignImportModal — clear assignment', () => {
  test('Clear assignment is disabled when the episode has nothing tracked', async () => {
    const target = episode({ id: 10, file_tracked: false })

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/episodes')) return mockResponse([target])
      return mockResponse(null)
    })

    render(
      createElement(AssignImportModal, { showId: 1, episode: target, onClose: vi.fn() }),
      { wrapper: makeWrapper() },
    )

    const clearButton = await screen.findByRole('button', { name: 'Clear assignment' })
    expect(clearButton).toBeDisabled()
  })

  test('Clear assignment calls DELETE .../tracking and closes on success', async () => {
    const other = episode({
      id: 11,
      episode_number: 2,
      file_tracked: true,
      tracked_filename: '/media/show/ep02.mkv',
      tracked_source: 'import',
    })
    const target = episode({
      id: 10,
      file_tracked: true,
      tracked_filename: '/media/show/ep01.mkv',
      tracked_source: 'import',
    })
    const onClose = vi.fn()
    let deleteCalled = false

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/episodes')) return mockResponse([target, other])
      if (url.includes('/tracking') && init?.method === 'DELETE') {
        deleteCalled = true
        return mockResponse({ ...target, file_tracked: false, tracked_filename: null })
      }
      return mockResponse(null)
    })

    render(
      createElement(AssignImportModal, { showId: 1, episode: target, onClose }),
      { wrapper: makeWrapper() },
    )

    const clearButton = await screen.findByRole('button', { name: 'Clear assignment' })
    expect(clearButton).not.toBeDisabled()
    fireEvent.click(clearButton)

    await waitFor(() => {
      expect(deleteCalled).toBe(true)
      expect(onClose).toHaveBeenCalled()
    })
  })
})
