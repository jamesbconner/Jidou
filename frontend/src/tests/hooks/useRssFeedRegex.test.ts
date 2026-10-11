import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { useSuggestFeedRegex, useTestFeedRegex } from '@/hooks/useRss'
import type { FeedRegexSuggestion, RegexMatchReportRead } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// See useShows.test.ts for why fetch is a plain assignment rather than vi.spyOn.
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

const report: RegexMatchReportRead = {
  matched_titles: ['Show - 05'],
  unmatched_titles: ['Show - 05 (720p)'],
  total: 2,
}

describe('useSuggestFeedRegex', () => {
  test('POSTs the group key and previous suggestions to the feed-scoped endpoint', async () => {
    const suggestion: FeedRegexSuggestion = {
      regex_include: 'Show.*1080p',
      regex_exclude: '',
      model: 'm',
      cached: false,
      match: report,
    }
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockResponse(suggestion))

    const { result } = renderHook(() => useSuggestFeedRegex(7), { wrapper: makeWrapper() })
    result.current.mutate({ parsed_name: 'Show', show_title: 'Show (2024)', previous: ['Old'] })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const [url, init] = vi.mocked(globalThis.fetch).mock.calls[0]
    expect(url).toBe('/api/rss/feeds/7/suggest-regex')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({
      parsed_name: 'Show',
      show_title: 'Show (2024)',
      previous: ['Old'],
    })
    expect(result.current.data?.match.total).toBe(2)
  })

  test('surfaces the backend error detail', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      mockResponse({ detail: 'LLM provider is not configured' }, 422),
    )

    const { result } = renderHook(() => useSuggestFeedRegex(7), { wrapper: makeWrapper() })
    result.current.mutate({ parsed_name: 'Show', previous: [] })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error?.message).toContain('LLM provider is not configured')
  })
})

describe('useTestFeedRegex', () => {
  test('POSTs the patterns and flags to the test endpoint', async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(mockResponse(report))

    const { result } = renderHook(() => useTestFeedRegex(7), { wrapper: makeWrapper() })
    result.current.mutate({
      parsed_name: 'Show',
      regex_include: 'Show.*1080p',
      regex_exclude: 'FRENCH',
      regex_include_ignorecase: false,
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const [url, init] = vi.mocked(globalThis.fetch).mock.calls[0]
    expect(url).toBe('/api/rss/feeds/7/test-regex')
    expect(JSON.parse(init?.body as string)).toMatchObject({
      parsed_name: 'Show',
      regex_include: 'Show.*1080p',
      regex_include_ignorecase: false,
    })
    expect(result.current.data).toEqual(report)
  })
})
