import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import RSS from '@/pages/RSS'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(MemoryRouter, null, children),
    )
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

function mockResponse(
  body: unknown = null,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: (k: string) => headers[k] ?? null } as unknown as Headers,
    json: async () => body,
    blob: async () => new Blob([JSON.stringify(body)]),
  } as unknown as Response
}

function mockRss({
  importStatus = 200,
  publishStatus = 200,
  downloadStatus = 200,
}: { importStatus?: number; publishStatus?: number; downloadStatus?: number } = {}) {
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/rss/feeds')) return mockResponse([])
    if (url.includes('/rss/subscriptions')) return mockResponse([])
    if (url.includes('/rss/import')) {
      return importStatus === 200
        ? mockResponse({ id: 1 })
        : mockResponse({ detail: 'Celery broker unreachable' }, importStatus)
    }
    if (url.includes('/rss/publish')) {
      return publishStatus === 200
        ? mockResponse({ id: 2 })
        : mockResponse({ detail: 'Celery broker unreachable' }, publishStatus)
    }
    if (url.includes('/rss/download')) {
      return downloadStatus === 200
        ? mockResponse(null, 200, { 'Content-Disposition': 'attachment; filename="yarss2.conf"' })
        : mockResponse({ detail: 'Disk full on remote host' }, downloadStatus)
    }
    return mockResponse([])
  })
}

describe('RSS page — dispatch/download failures surface inline errors', () => {
  test('a failed import dispatch shows an inline error, not silence', async () => {
    mockRss({ importStatus: 500 })
    render(<RSS />, { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Import from server' }))

    await waitFor(() => {
      expect(screen.getByText(/Import failed to start/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Celery broker unreachable/)).toBeInTheDocument()
  })

  test('a failed publish dispatch shows an inline error, not silence', async () => {
    mockRss({ publishStatus: 500 })
    render(<RSS />, { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Publish to server' }))

    await waitFor(() => {
      expect(screen.getByText(/Publish failed to start/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Celery broker unreachable/)).toBeInTheDocument()
  })

  test('a failed download shows an inline error, not silence', async () => {
    mockRss({ downloadStatus: 500 })
    render(<RSS />, { wrapper: makeWrapper() })

    fireEvent.click(await screen.findByRole('button', { name: 'Download' }))

    await waitFor(() => {
      expect(screen.getByText(/Download failed/)).toBeInTheDocument()
    })
    expect(screen.getByText(/Disk full on remote host/)).toBeInTheDocument()
  })
})
