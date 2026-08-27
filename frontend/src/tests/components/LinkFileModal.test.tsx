import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { LinkFileModal } from '@/components/LinkFileModal'
import type { EpisodeList, FileRead } from '@/types/api'

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
    episode_number: 8,
    name: 'Episode',
    file_tracked: false,
    tracked_source: null,
    tracked_filename: null,
    watched: false,
    backing_files: [],
    tracked_filename_display: null,
    ...over,
  }
}

function file(over: Partial<FileRead>): FileRead {
  return {
    id: 100,
    original_filename: '/media/show/s01e08.mkv',
    remote_path: '/media/show/s01e08.mkv',
    file_size: 123,
    status: 'unmatched',
    show_id: 1,
    episode_id: null,
    show: null,
    episode: null,
    parsed_show_name: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    matched_by: null,
    error_message: null,
    ...over,
  } as FileRead
}

describe('LinkFileModal — combined unmatched + imported pool', () => {
  test('lists both unmatched files and imported filenames as separate groups', async () => {
    const target = episode({ id: 10 })
    const otherEp = episode({
      id: 11,
      episode_number: 2,
      file_tracked: true,
      tracked_filename: '/media/show/ep02.mkv',
      tracked_source: 'import',
    })
    const unmatchedFile = file({ id: 100, original_filename: '/media/show/s01e08-real.mkv' })

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/config')) return mockResponse({})
      if (url.includes('/shows/1/episodes')) return mockResponse([target, otherEp])
      if (url.includes('/files') && url.includes('status=unmatched')) {
        return mockResponse([unmatchedFile])
      }
      return mockResponse(null)
    })

    render(
      createElement(LinkFileModal, {
        showId: 1,
        showLocalPath: null,
        episode: target,
        onClose: vi.fn(),
      }),
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByText('s01e08-real.mkv')).toBeInTheDocument()
    expect(screen.getByText(/ep02\.mkv/)).toBeInTheDocument()
    expect(document.querySelector('optgroup[label="Unmatched"]')).not.toBeNull()
    expect(document.querySelector('optgroup[label="Imported"]')).not.toBeNull()
  })

  test('picking an unmatched file PATCHes the file with the target episode', async () => {
    const target = episode({ id: 10 })
    const unmatchedFile = file({ id: 100, original_filename: '/media/show/s01e08-real.mkv' })
    const onClose = vi.fn()
    let patchBody: unknown = null

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/config')) return mockResponse({})
      if (url.includes('/shows/1/episodes')) return mockResponse([target])
      if (url.includes('/files') && url.includes('status=unmatched')) {
        return mockResponse([unmatchedFile])
      }
      if (url.endsWith('/files/100') && init?.method === 'PATCH') {
        patchBody = JSON.parse(String(init.body))
        return mockResponse({ ...unmatchedFile, episode_id: target.id, status: 'matched' })
      }
      return mockResponse(null)
    })

    render(
      createElement(LinkFileModal, {
        showId: 1,
        showLocalPath: null,
        episode: target,
        onClose,
      }),
      { wrapper: makeWrapper() },
    )

    const select = await screen.findByRole('combobox')
    await screen.findByRole('option', { name: 's01e08-real.mkv' })
    fireEvent.change(select, { target: { value: 'u:100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(patchBody).toMatchObject({ episode_id: target.id, status: 'matched' })
      expect(onClose).toHaveBeenCalled()
    })
  })

  test('picking an imported filename calls assign-import instead of PATCH', async () => {
    const target = episode({ id: 10 })
    const otherEp = episode({
      id: 11,
      episode_number: 2,
      file_tracked: true,
      tracked_filename: '/media/show/ep02.mkv',
      tracked_source: 'import',
    })
    const onClose = vi.fn()
    let assignImportCalled = false
    let assignImportBody: unknown = null

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/assign-import') && init?.method === 'POST') {
        assignImportCalled = true
        assignImportBody = JSON.parse(String(init.body))
        return mockResponse({ ok: true })
      }
      if (url.includes('/config')) return mockResponse({})
      if (url.endsWith('/shows/1/episodes')) return mockResponse([target, otherEp])
      if (url.includes('/files') && url.includes('status=unmatched')) {
        return mockResponse([])
      }
      return mockResponse(null)
    })

    render(
      createElement(LinkFileModal, {
        showId: 1,
        showLocalPath: null,
        episode: target,
        onClose,
      }),
      { wrapper: makeWrapper() },
    )

    const select = await screen.findByRole('combobox')
    await screen.findByRole('option', { name: /ep02\.mkv/ })
    fireEvent.change(select, { target: { value: 'i:/media/show/ep02.mkv' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => {
      expect(assignImportCalled).toBe(true)
      expect(assignImportBody).toMatchObject({ filename: '/media/show/ep02.mkv' })
      expect(onClose).toHaveBeenCalled()
    })
  })
})
