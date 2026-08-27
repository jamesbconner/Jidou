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

describe('LinkFileModal — combined existing-file + imported pool', () => {
  test('lists orphaned routed files alongside imported filenames, but excludes in-flight files', async () => {
    const target = episode({ id: 10 })
    const otherEp = episode({
      id: 11,
      episode_number: 2,
      file_tracked: true,
      tracked_filename: '/media/show/ep02.mkv',
      tracked_source: 'import',
    })
    // Displaced by a mis-route: stays 'routed', episode_id cleared — this is
    // the case the dropdown previously failed to surface.
    const routedFile = file({
      id: 100,
      original_filename: '/media/show/s01e08-real.mkv',
      status: 'routed',
    })
    // Still mid-transfer — must never appear as pickable.
    const downloadingFile = file({
      id: 101,
      original_filename: '/media/show/in-flight.mkv',
      status: 'downloading',
    })

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/config')) return mockResponse({})
      if (url.endsWith('/shows/1/episodes')) return mockResponse([target, otherEp])
      if (url.includes('/files') && url.includes('show_id=1')) {
        return mockResponse([routedFile, downloadingFile])
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

    expect(await screen.findByText(/s01e08-real\.mkv/)).toBeInTheDocument()
    expect(screen.getByText(/ep02\.mkv/)).toBeInTheDocument()
    expect(screen.queryByText(/in-flight\.mkv/)).not.toBeInTheDocument()
    expect(document.querySelector('optgroup[label="Existing files"]')).not.toBeNull()
    expect(document.querySelector('optgroup[label="Imported"]')).not.toBeNull()
  })

  test('picking an orphaned routed file PATCHes it onto the target episode', async () => {
    const target = episode({ id: 10 })
    const routedFile = file({
      id: 100,
      original_filename: '/media/show/s01e08-real.mkv',
      status: 'routed',
    })
    const onClose = vi.fn()
    let patchBody: unknown = null

    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.includes('/config')) return mockResponse({})
      if (url.endsWith('/shows/1/episodes')) return mockResponse([target])
      if (url.includes('/files') && url.includes('show_id=1')) {
        return mockResponse([routedFile])
      }
      if (url.endsWith('/files/100') && init?.method === 'PATCH') {
        patchBody = JSON.parse(String(init.body))
        return mockResponse({ ...routedFile, episode_id: target.id, status: 'matched' })
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
    await screen.findByRole('option', { name: /s01e08-real\.mkv/ })
    fireEvent.change(select, { target: { value: 'e:100' } })
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
      if (url.includes('/files') && url.includes('show_id=1')) {
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
