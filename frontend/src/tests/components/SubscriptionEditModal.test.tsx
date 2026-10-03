import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import type { RssFeedRead, RssSubscriptionRead } from '@/types/api'

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
  return { ok: status < 300, status, statusText: '', json: async () => body } as Response
}

const feeds = [
  { id: 1, name: 'Default Feed' },
  { id: 2, name: 'Hinted Feed' },
] as RssFeedRead[]

function stubSub(): RssSubscriptionRead {
  return {
    id: 7,
    name: 'New Show',
    remote_key: null,
    feed_id: 1,
    show_id: null,
    show: null,
    active: false,
    enabled_in_config: false,
    regex_include: null,
    regex_exclude: null,
    regex_include_ignorecase: true,
    regex_exclude_ignorecase: true,
    download_location: null,
    move_completed: null,
    label: null,
    last_match: null,
  } as unknown as RssSubscriptionRead
}

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(
        MemoryRouter,
        null,
        createElement(SubscriptionEditModal, { sub: stubSub(), feeds, onClose: vi.fn() }),
      ),
    ),
  )
}

describe('SubscriptionEditModal — unsaved edits', () => {
  test('Active unlocks as soon as "Enabled in config" is ticked on a stub', () => {
    vi.mocked(fetch).mockImplementation(async () => mockResponse([]))
    renderModal()

    const active = screen.getByLabelText('Active') as HTMLInputElement
    expect(active.disabled).toBe(true)

    fireEvent.click(screen.getByLabelText('Enabled in config'))

    expect(active.disabled).toBe(false)
  })

  test('Suggest sends the feed currently selected in the form, not the saved one', async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes('/suggest-regex')) {
        return mockResponse({ regex_include: 'a', regex_exclude: 'b', model: 'm', cached: false })
      }
      return mockResponse([])
    })
    renderModal()

    fireEvent.change(screen.getByDisplayValue('Default Feed'), { target: { value: '2' } })
    fireEvent.click(screen.getByText('Suggest via LLM'))
    fireEvent.click(screen.getByRole('button', { name: 'Suggest' }))

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(([url]) => String(url).includes('/suggest-regex'))
      expect(call).toBeDefined()
      expect(JSON.parse(String(call![1]?.body))).toEqual({ feed_id: 2 })
    })
  })
})
