import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useConnectionTest, useTriggerWithDryRun } from '@/hooks/useSettingsActions'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(MemoryRouter, null, children))
}

function mockResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, statusText: 'err', json: async () => body } as Response
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('useConnectionTest', () => {
  test.each(['tmdb', 'sftp', 'redis', 'llm'] as const)('POSTs /config/test/%s', async (service) => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ ok: true, message: '5ms' }))
    const { result } = renderHook(() => useConnectionTest(service), { wrapper: makeWrapper() })

    act(() => result.current.mutate())
    await waitFor(() => expect(result.current.data).toEqual({ ok: true, message: '5ms' }))

    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url as string).toContain(`/api/config/test/${service}`)
    expect((init as RequestInit).method).toBe('POST')
  })

  test('surfaces a failed request as the mutation error', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ detail: 'boom' }, false, 500))
    const { result } = renderHook(() => useConnectionTest('tmdb'), { wrapper: makeWrapper() })

    act(() => result.current.mutate())
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error?.message).toContain('boom')
  })
})

describe('useTriggerWithDryRun', () => {
  function useHarness(taskType: 'seed' | 'backfill_show_metadata') {
    return { actions: useTriggerWithDryRun(taskType), location: useLocation() }
  }

  test.each([
    ['seed', 'dryRun', true],
    ['seed', 'live', false],
    ['backfill_show_metadata', 'dryRun', true],
    ['backfill_show_metadata', 'live', false],
  ] as const)('%s %s trigger sends dry_run=%s and navigates to the task', async (taskType, which, dry) => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ id: 42, status: 'pending' }))
    const { result } = renderHook(() => useHarness(taskType), {
      wrapper: makeWrapper(),
    })

    act(() => result.current.actions[which].mutate())
    await waitFor(() => expect(result.current.location.pathname).toBe('/tasks'))

    expect(result.current.location.search).toBe('?highlight=42')
    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url as string).toContain('/api/tasks/trigger')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      task_type: taskType,
      dry_run: dry,
    })
  })

  test('firing one mutation leaves the other idle', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ id: 1, status: 'pending' }))
    const { result } = renderHook(() => useHarness('seed'), { wrapper: makeWrapper() })

    act(() => result.current.actions.dryRun.mutate())
    await waitFor(() => expect(result.current.actions.dryRun.isSuccess).toBe(true))
    expect(result.current.actions.live.isPending).toBe(false)
    expect(result.current.actions.live.data).toBeUndefined()
  })
})
