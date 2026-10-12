import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import RSS from '@/pages/RSS'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of the RSS page: header/task-badge/error DOM, every
 * subscription filter combination, tab switching with retained filters, and the
 * request sequence. Written before the header/filter extraction; it must pass
 * unchanged afterwards.
 */

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(MemoryRouter, null, children))
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
  vi.spyOn(Date.prototype, 'toLocaleString').mockReturnValue('DATE')
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const sub = (id: number, name: string, over: Record<string, unknown> = {}) => ({
  id,
  name,
  remote_key: String(id),
  feed_id: null,
  show_id: null,
  show: null,
  active: true,
  enabled_in_config: true,
  regex_include: null,
  regex_exclude: null,
  regex_include_ignorecase: true,
  regex_exclude_ignorecase: true,
  download_location: null,
  move_completed: null,
  label: null,
  last_match: null,
  extra_config: null,
  feed: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  ...over,
})

const subs = [
  sub(1, 'Alpha Linked', { feed_id: 10 }),
  sub(2, 'Beta Stub', { remote_key: null, enabled_in_config: false, active: false }),
  sub(3, 'Gamma Unlinked', { active: false }),
  sub(4, 'Delta Disabled', { enabled_in_config: false, feed_id: 11 }),
]
const feeds = [
  { id: 10, name: 'Feed Ten', url: 'https://t.example/10', active: true, subscription_count: 1 },
  { id: 11, name: 'Feed Eleven', url: 'https://t.example/11', active: false, subscription_count: 1 },
]

interface Opts {
  importStatus?: number
  publishStatus?: number
  downloadStatus?: number
  diffStatus?: number
  diffChanges?: boolean
  taskStatus?: string
}

function mockApi(opts: Opts = {}): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.includes('/rss/feeds')) return mockResponse(feeds)
    if (url.includes('/rss/subscriptions/recommendations')) return mockResponse([])
    if (url.includes('/rss/subscriptions')) return mockResponse(subs)
    if (url.includes('/rss/import'))
      return opts.importStatus ? mockResponse({ detail: 'import boom' }, opts.importStatus) : mockResponse({ id: 1 })
    if (url.includes('/rss/publish'))
      return opts.publishStatus ? mockResponse({ detail: 'publish boom' }, opts.publishStatus) : mockResponse({ id: 2 })
    if (url.includes('/rss/download'))
      return opts.downloadStatus
        ? mockResponse({ detail: 'download boom' }, opts.downloadStatus)
        : ({
            ...mockResponse(null),
            headers: { get: () => 'attachment; filename="y.conf"' },
            blob: async () => new Blob(['x']),
          } as unknown as Response)
    if (url.includes('/rss/diff'))
      return opts.diffStatus
        ? mockResponse({ detail: 'diff boom' }, opts.diffStatus)
        : mockResponse({
            snapshot_id: 3,
            snapshot_type: 'upload',
            snapshot_created_at: '2026-01-01T00:00:00Z',
            has_changes: opts.diffChanges ?? true,
            diff: ['--- a', '+++ b', '@@ -1 +1 @@', '-old', '+new', ' same'],
          })
    if (url.includes('/tasks/'))
      return mockResponse({ id: Number(url.split('/').pop()), status: opts.taskStatus ?? 'completed', progress_message: 'all done' })
    return mockResponse([])
  })
  return log
}

async function renderPage() {
  render(<RSS />, { wrapper: makeWrapper() })
  await screen.findByText('Alpha Linked')
}

describe('RSS characterization', () => {
  test('default page DOM and mount requests', async () => {
    const log = mockApi()
    await renderPage()
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('loading state before subscriptions arrive', () => {
    mockApi()
    render(<RSS />, { wrapper: makeWrapper() })
    expect(domSnapshot()).toMatchSnapshot('loading')
  })

  test.each([
    ['name', { nameSearch: 'ALPHA' }],
    ['enabled', { enabledFilter: 'enabled' }],
    ['disabled', { enabledFilter: 'disabled' }],
    ['active', { activeFilter: 'active' }],
    ['inactive', { activeFilter: 'inactive' }],
    ['stub', { keyFilter: 'stub' }],
    ['keyed', { keyFilter: 'keyed' }],
    ['unlinked', { feedFilter: 'unlinked' }],
    ['feed ten', { feedFilter: 10 }],
    ['combined', { enabledFilter: 'enabled', activeFilter: 'inactive', keyFilter: 'keyed', feedFilter: 'unlinked' }],
  ])('stored filter: %s', async (_name, filters) => {
    window.localStorage.setItem(
      'jidou:rss-filters',
      JSON.stringify({ nameSearch: '', enabledFilter: 'all', activeFilter: 'all', keyFilter: 'all', feedFilter: 'all', ...filters }),
    )
    mockApi()
    render(<RSS />, { wrapper: makeWrapper() })
    await screen.findByText(/\d+ \/ 4/)
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('changing every filter control persists and is retained across tab switches', async () => {
    mockApi()
    await renderPage()
    fireEvent.change(screen.getByPlaceholderText('Search name…'), { target: { value: 'a' } })
    const selects = screen.getAllByRole('combobox')
    expect(selects).toHaveLength(4)
    fireEvent.change(selects[0], { target: { value: 'enabled' } })
    fireEvent.change(selects[1], { target: { value: 'active' } })
    fireEvent.change(selects[2], { target: { value: 'keyed' } })
    fireEvent.change(selects[3], { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: /^Feeds/ }))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('feeds tab')
    fireEvent.click(screen.getByRole('button', { name: 'Recommendations' }))
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('recommendations tab')
    fireEvent.click(screen.getByRole('button', { name: /^Subscriptions/ }))
    expect((screen.getByPlaceholderText('Search name…') as HTMLInputElement).value).toBe('a')
    fireEvent.change(selects[3], { target: { value: 'all' } })
    fireEvent.change(selects[3], { target: { value: 'unlinked' } })
    expect(JSON.parse(window.localStorage.getItem('jidou:rss-filters') ?? '{}')).toMatchSnapshot('stored')
  })

  test('import and publish dispatch show polled task badges', async () => {
    const log = mockApi({ taskStatus: 'running' })
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Import from server' }))
    await screen.findByText(/Import:/)
    fireEvent.click(screen.getByRole('button', { name: 'Publish to server' }))
    await screen.findByText(/Publish:/)
    await waitFor(() => expect(document.body.textContent).toContain('running — all done'))
    expect(domSnapshot()).toMatchSnapshot('dom')
    expect(log.filter((l) => !l.startsWith('GET /api/rss/feeds') && !l.includes('subscriptions')).slice(0, 4)).toMatchSnapshot('dispatch requests')
  })

  test('all four failures render together', async () => {
    mockApi({ importStatus: 500, publishStatus: 500, downloadStatus: 500, diffStatus: 500 })
    await renderPage()
    for (const name of ['Import from server', 'Publish to server', 'Download', 'Diff']) {
      fireEvent.click(screen.getByRole('button', { name }))
    }
    await screen.findByText(/Diff failed/)
    await screen.findByText(/Import failed to start/)
    await screen.findByText(/Publish failed to start/)
    await screen.findByText(/Download failed/)
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test.each([[true], [false]])('diff modal (has_changes=%s) opens and closes', async (has) => {
    mockApi({ diffChanges: has })
    await renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Diff' }))
    await screen.findByRole('dialog')
    expect(domSnapshot()).toMatchSnapshot('dom')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
