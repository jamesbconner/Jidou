import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Files from '@/pages/Files'
import type { FileRead } from '@/types/api'

function makeFile(overrides: Partial<FileRead> = {}): FileRead {
  return {
    id: 1,
    show_id: null,
    episode_id: null,
    original_filename: 'show.s01e01.mkv',
    remote_path: '/shows/show.s01e01.mkv',
    local_path: null,
    file_size: 1_000_000,
    hash_sha256: null,
    status: 'discovered',
    matched_by: null,
    ignored_reason: null,
    error_message: null,
    parsed_show_name: null,
    parsed_season: null,
    parsed_episode: null,
    parsed_confidence: null,
    parsed_content_type: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    show: null,
    episode: null,
    ...overrides,
  } as FileRead
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      MemoryRouter,
      {},
      createElement(QueryClientProvider, { client: qc }, children),
    )
}

// See Watchlist.test.tsx for why a plain assignment (not vi.spyOn) is used here.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function mockResponse(body: unknown, total: number, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: (name: string) => (name === 'X-Total-Count' ? String(total) : null) },
    json: async () => body,
  } as unknown as Response
}

function mockFiles(total: number) {
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/files?')) {
      const params = new URLSearchParams(url.split('?')[1])
      const limit = Number(params.get('limit'))
      const offset = Number(params.get('offset'))
      const remaining = Math.max(0, total - offset)
      const count = Math.min(limit, remaining)
      return mockResponse(
        Array.from({ length: count }, (_, i) => makeFile({ id: offset + i + 1 })),
        total,
      )
    }
    return mockResponse([], 0)
  })
}

function lastFilesUrl(): string {
  const calls = vi.mocked(fetch).mock.calls.filter((c) => String(c[0]).includes('/files?'))
  return String(calls[calls.length - 1]?.[0])
}

describe('Files page — ignored files visibility', () => {
  test('does not request show_ignored by default', async () => {
    mockFiles(1)
    render(<Files />, { wrapper: makeWrapper() })

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0))
    const params = new URLSearchParams(lastFilesUrl().split('?')[1])
    expect(params.get('show_ignored')).toBeNull()
  })

  test('toggling "Show ignored" requests show_ignored=true', async () => {
    mockFiles(1)
    render(<Files />, { wrapper: makeWrapper() })

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('switch', { name: /show ignored files/i }))

    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('show_ignored')).toBe('true')
    })
  })
})

describe('Files page — Per page / Max records controls', () => {
  test('lowering max records reduces the number of rows fetched', async () => {
    mockFiles(200)
    render(<Files />, { wrapper: makeWrapper() })

    // Default maxRecords=null (all) with pageSize=100 -> 100 rows requested.
    fireEvent.change(screen.getByLabelText('Per page'), { target: { value: '100' } })
    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('limit')).toBe('100')
    })

    const maxRecordsSelect = screen.getByLabelText('Max records') as HTMLSelectElement
    fireEvent.change(maxRecordsSelect, { target: { value: '50' } })

    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('limit')).toBe('50')
    })
  })

  test('changing per page updates the requested limit', async () => {
    mockFiles(50)
    render(<Files />, { wrapper: makeWrapper() })

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0))

    const pageSizeSelect = screen.getByLabelText('Per page') as HTMLSelectElement
    fireEvent.change(pageSizeSelect, { target: { value: '10' } })

    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('limit')).toBe('10')
    })
  })

  test('summary label reflects the max records cap', async () => {
    mockFiles(200)
    render(<Files />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByLabelText('Max records')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Max records'), { target: { value: '50' } })

    await waitFor(() => {
      expect(screen.getByText(/50 of 200 files/)).toBeInTheDocument()
    })
  })

  test('raising per page while on a later page settles on a valid limit/offset, never zero', async () => {
    mockFiles(500)
    render(<Files />, { wrapper: makeWrapper() })

    fireEvent.change(screen.getByLabelText('Max records'), { target: { value: '50' } })
    fireEvent.change(screen.getByLabelText('Per page'), { target: { value: '10' } })

    // Jump to the last of 5 pages (offset=40) within the 50-record cap.
    await waitFor(() => expect(screen.getByTitle('Last page')).toBeInTheDocument())
    fireEvent.click(screen.getByTitle('Last page'))
    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('offset')).toBe('40')
    })

    // Raising per-page to 100 makes the stale offset (400) exceed the
    // 50-record cap — this must reset to page 0, not request limit=0.
    fireEvent.change(screen.getByLabelText('Per page'), { target: { value: '100' } })

    await waitFor(() => {
      const params = new URLSearchParams(lastFilesUrl().split('?')[1])
      expect(params.get('limit')).toBe('50')
      expect(params.get('offset')).toBe('0')
    })

    const zeroLimitCall = vi.mocked(fetch).mock.calls.find((c) => {
      const url = String(c[0])
      if (!url.includes('/files?')) return false
      return new URLSearchParams(url.split('?')[1]).get('limit') === '0'
    })
    expect(zeroLimitCall).toBeUndefined()
  })
})

describe('Files page — filter persistence', () => {
  test('per page, max records, and show-ignored choices persist to localStorage', async () => {
    mockFiles(1)
    render(<Files />, { wrapper: makeWrapper() })

    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(0))

    fireEvent.change(screen.getByLabelText('Per page'), { target: { value: '20' } })
    fireEvent.change(screen.getByLabelText('Max records'), { target: { value: '100' } })
    fireEvent.click(screen.getByRole('switch', { name: /show ignored files/i }))

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem('jidou:files-filters') ?? '{}')
      expect(stored).toMatchObject({ pageSize: 20, maxRecords: 100, showIgnored: true })
    })
  })
})
