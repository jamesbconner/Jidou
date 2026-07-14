import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Tasks from '@/pages/Tasks'
import type { TaskList } from '@/types/api'

function makeTask(id: number): TaskList {
  return {
    id,
    task_type: 'scan',
    status: 'completed',
    progress_current: 1,
    progress_total: 1,
    progress_message: null,
    result_summary: null,
    dry_run: false,
    created_at: '2026-06-01T00:00:00Z',
    completed_at: '2026-06-01T00:01:00Z',
  }
}

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

function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

function mockTasks(total: number) {
  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/tasks/count')) {
      return mockResponse({ total })
    }
    if (url.includes('active_only=true')) {
      return mockResponse([])
    }
    if (url.includes('/tasks?')) {
      const params = new URLSearchParams(url.split('?')[1])
      const limit = Number(params.get('limit'))
      const offset = Number(params.get('offset'))
      const remaining = Math.max(0, total - offset)
      const count = Math.min(limit, remaining)
      return mockResponse(Array.from({ length: count }, (_, i) => makeTask(offset + i + 1)))
    }
    return mockResponse([])
  })
}

describe('Tasks page — Max records control', () => {
  test('lowering max records reduces the number of task cards fetched', async () => {
    mockTasks(50)
    render(<Tasks />, { wrapper: makeWrapper() })

    // Default maxRecords=200, pageSize=20 -> 20 cards on page 1.
    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.filter((c) => String(c[0]).includes('/tasks?'))
      expect(calls.length).toBeGreaterThan(0)
    })
    await waitFor(() => {
      expect(document.querySelectorAll('.space-y-2 > div').length).toBe(20)
    })

    // Selects in DOM order: task type (trigger form), filter by type, per
    // page, max records — no htmlFor/id association, so index into comboboxes.
    const maxRecordsSelect = screen.getAllByRole('combobox')[3] as HTMLSelectElement
    fireEvent.change(maxRecordsSelect, { target: { value: '5' } })

    // With maxRecords=5 the fetched page must be truncated to 5, not 20.
    await waitFor(() => {
      expect(document.querySelectorAll('.space-y-2 > div').length).toBe(5)
    })

    const lastCall = vi
      .mocked(fetch)
      .mock.calls.filter((c) => String(c[0]).includes('/tasks?') && !String(c[0]).includes('active_only'))
      .pop()
    const lastUrl = String(lastCall?.[0])
    const params = new URLSearchParams(lastUrl.split('?')[1])
    expect(params.get('limit')).toBe('5')
  })

  test('summary label reflects the max records cap', async () => {
    mockTasks(50)
    render(<Tasks />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getAllByRole('combobox').length).toBeGreaterThan(0))
    const maxRecordsSelect = screen.getAllByRole('combobox')[3] as HTMLSelectElement
    fireEvent.change(maxRecordsSelect, { target: { value: '5' } })

    await waitFor(() => {
      expect(screen.getByText('5 of 50 tasks')).toBeInTheDocument()
    })
  })
})
