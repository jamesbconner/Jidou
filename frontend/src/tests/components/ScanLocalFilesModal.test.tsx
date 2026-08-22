import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ScanLocalFilesModal } from '@/components/ScanLocalFilesModal'
import type { EpisodeList, ScannedFileMatch } from '@/types/api'

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
    tracked_source: null,
    watched: false,
    backing_files: [],
    tracked_filename_display: null,
    ...over,
  }
}

function scannedFile(over: Partial<ScannedFileMatch>): ScannedFileMatch {
  return {
    path: '/media/show/ep.mkv',
    filename: 'ep.mkv',
    season: 1,
    episode_number: 1,
    episode: null,
    status: 'unmatched',
    ...over,
  }
}

describe('ScanLocalFilesModal — replace flow', () => {
  test('selecting an untracked episode shows a plain Link button with no replace flag', async () => {
    const untracked = episode({ id: 10, episode_number: 1, file_tracked: false })
    const tracked = episode({ id: 11, episode_number: 2, file_tracked: true })
    const rows = [scannedFile({ path: '/media/show/ep02-new.mkv', filename: 'ep02-new.mkv' })]
    let linkBody: { episode_id?: number; path: string; replace?: boolean } | undefined

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/episodes')) return mockResponse([untracked, tracked])
      if (url.includes('/scan-local-files')) return mockResponse(rows)
      if (url.includes('/link-file')) {
        linkBody = JSON.parse(String(init?.body)) as typeof linkBody
        return mockResponse({ id: 1, original_filename: 'ep02-new.mkv', status: 'routed' })
      }
      return mockResponse(null)
    })

    render(createElement(ScanLocalFilesModal, { showId: 1, onClose: vi.fn() }), {
      wrapper: makeWrapper(),
    })

    const select = await screen.findByRole('combobox')
    fireEvent.change(select, { target: { value: '10' } })

    const linkButton = screen.getByRole('button', { name: 'Link' })
    fireEvent.click(linkButton)

    await waitFor(() => {
      expect(screen.getByText('linked')).toBeInTheDocument()
    })
    expect(linkBody?.replace).toBeUndefined()
  })

  test('selecting an already-tracked episode switches to Link (replace) and sends replace=true', async () => {
    const untracked = episode({ id: 10, episode_number: 1, file_tracked: false })
    const tracked = episode({ id: 11, episode_number: 2, file_tracked: true })
    const rows = [scannedFile({ path: '/media/show/ep02-moved.mkv', filename: 'ep02-moved.mkv' })]
    let linkBody: { episode_id?: number; path: string; replace?: boolean } | undefined

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/episodes')) return mockResponse([untracked, tracked])
      if (url.includes('/scan-local-files')) return mockResponse(rows)
      if (url.includes('/link-file')) {
        linkBody = JSON.parse(String(init?.body)) as typeof linkBody
        return mockResponse({ id: 1, original_filename: 'ep02-moved.mkv', status: 'routed' })
      }
      return mockResponse(null)
    })

    render(createElement(ScanLocalFilesModal, { showId: 1, onClose: vi.fn() }), {
      wrapper: makeWrapper(),
    })

    const select = await screen.findByRole('combobox')
    fireEvent.change(select, { target: { value: '11' } })

    expect(
      screen.getByText(/already tracked.*Link \(replace\).*unlinks its/i),
    ).toBeInTheDocument()

    const replaceButton = screen.getByRole('button', { name: 'Link (replace)' })
    fireEvent.click(replaceButton)

    await waitFor(() => {
      expect(linkBody?.replace).toBe(true)
    })
    expect(linkBody?.path).toBe('/media/show/ep02-moved.mkv')
  })

  test('"Confirm All Matched" only counts rows resolvable without replace', async () => {
    const untracked = episode({ id: 10, episode_number: 1, file_tracked: false })
    const tracked = episode({ id: 11, episode_number: 2, file_tracked: true })
    const rows = [
      scannedFile({
        path: '/media/show/ep01.mkv',
        filename: 'ep01.mkv',
        episode_number: 1,
        episode: {
          id: 10,
          season_number: 1,
          episode_number: 1,
          name: 'Episode',
        },
        status: 'matched',
      }),
      scannedFile({
        path: '/media/show/ep02-moved.mkv',
        filename: 'ep02-moved.mkv',
        episode_number: 2,
        episode: {
          id: 11,
          season_number: 1,
          episode_number: 2,
          name: 'Episode',
        },
        status: 'conflict',
      }),
    ]

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/episodes')) return mockResponse([untracked, tracked])
      if (url.includes('/scan-local-files')) return mockResponse(rows)
      return mockResponse(null)
    })

    render(createElement(ScanLocalFilesModal, { showId: 1, onClose: vi.fn() }), {
      wrapper: makeWrapper(),
    })

    // The conflict row's proposed episode is already tracked, so it's seeded
    // blank (see ScanLocalFilesModal's seeding effect) and excluded from the
    // bulk count even though a proposal exists — only the plain-matched row
    // (ep 10, untracked) counts.
    expect(await screen.findByText('Confirm All Matched (1)')).toBeInTheDocument()
  })
})
