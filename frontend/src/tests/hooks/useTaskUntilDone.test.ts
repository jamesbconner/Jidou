import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { TERMINAL_TASK_STATUSES, useTaskUntilDone } from '@/hooks/useTasks'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

function mockResponse(body: unknown): Response {
  return { ok: true, status: 200, statusText: '', json: async () => body } as Response
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('TERMINAL_TASK_STATUSES', () => {
  test('contains exactly the three terminal statuses', () => {
    expect([...TERMINAL_TASK_STATUSES].sort()).toEqual(['cancelled', 'completed', 'failed'])
  })
})

describe('useTaskUntilDone', () => {
  test('polls until the task completes, then stops', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(mockResponse({ id: 7, status: 'pending' }))
      .mockResolvedValueOnce(mockResponse({ id: 7, status: 'running' }))
      .mockResolvedValue(mockResponse({ id: 7, status: 'completed' }))

    const { result } = renderHook(() => useTaskUntilDone(7, { intervalMs: 20 }), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.data?.status).toBe('completed'))
    expect(fetch).toHaveBeenCalledTimes(3)
    expect(vi.mocked(fetch).mock.calls[0][0] as string).toContain('/api/tasks/7')

    // Several intervals later no further request has been made.
    await new Promise((r) => setTimeout(r, 120))
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  test('stops polling on a failed status too', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ id: 8, status: 'failed' }))
    const { result } = renderHook(() => useTaskUntilDone(8, { intervalMs: 20 }), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.data?.status).toBe('failed'))
    await new Promise((r) => setTimeout(r, 100))
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  test.each([null, 0])('makes no request when id is %s', async (id) => {
    const { result } = renderHook(() => useTaskUntilDone(id, { intervalMs: 20 }), {
      wrapper: makeWrapper(),
    })
    await new Promise((r) => setTimeout(r, 80))
    expect(result.current.fetchStatus).toBe('idle')
    expect(fetch).not.toHaveBeenCalled()
  })
})
