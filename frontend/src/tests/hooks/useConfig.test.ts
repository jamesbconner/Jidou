import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { configKeys, useConfig } from '@/hooks/useConfig'

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

describe('useConfig', () => {
  test('keeps the historical ["config"] cache key', () => {
    expect(configKeys.all).toEqual(['config'])
  })

  test('two hooks mounted together share one request', async () => {
    vi.mocked(fetch).mockResolvedValue(mockResponse({ media_paths: {} }))
    const { result } = renderHook(() => ({ a: useConfig(), b: useConfig() }), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.a.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.b.isSuccess).toBe(true))

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(vi.mocked(fetch).mock.calls[0][0] as string).toContain('/api/config')
  })
})
