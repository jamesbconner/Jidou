import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Files from '@/pages/Files'
import { domSnapshot, sleep } from '../helpers/dom'

/**
 * Characterization of the Files page: row DOM per file status, the footer
 * summary, filters with page reset, pagination and maxRecords truncation, the
 * inline editors, and the request sequence. Written before the table/toolbar
 * extraction; it must pass unchanged afterwards.
 */

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(MemoryRouter, {}, createElement(QueryClientProvider, { client: qc }, children))
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  globalThis.fetch = vi.fn()
  window.localStorage.clear()
  // Locale/timezone-dependent; pin it so snapshots are stable across machines.
  vi.spyOn(Date.prototype, 'toLocaleString').mockReturnValue('DATE')
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function res(body: unknown, total = 0, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    headers: { get: (name: string) => (name === 'X-Total-Count' ? String(total) : null) },
    json: async () => body,
  } as unknown as Response
}

const file = (overrides: Record<string, unknown>) => ({
  id: 1,
  show_id: null,
  episode_id: null,
  original_filename: 'show.s01e01.mkv',
  remote_path: '/shows/show.s01e01.mkv',
  file_size: 1_000_000,
  status: 'discovered',
  error_message: null,
  parsed_show_name: null,
  created_at: '2026-01-01T00:00:00Z',
  show: null,
  episode: null,
  ...overrides,
})

const showBrief = { id: 5, title: 'Example Show' }
const episodeBrief = { id: 50, season_number: 1, episode_number: 2, name: 'Second' }

const mixedRows = [
  file({ id: 1, status: 'unmatched', parsed_show_name: 'Parsed Name', file_size: 512 }),
  file({ id: 2, status: 'error', error_message: 'boom happened', show_id: 5, show: showBrief, episode_id: 50, episode: episodeBrief, file_size: 2048 }),
  file({ id: 3, status: 'routed', show_id: 5, show: showBrief, episode_id: 50, episode: episodeBrief, file_size: 5 * 1024 ** 2 }),
  file({ id: 4, status: 'downloading', show_id: 5, show: showBrief, file_size: 3 * 1024 ** 3 }),
  file({ id: 5, status: 'matched', show_id: 9, show: null, file_size: 1536 * 1024 }),
  file({ id: 6, status: 'unmatched', show_id: 5, show: showBrief }),
  file({ id: 7, status: 'matched', show_id: null }),
]

interface Setup {
  rows?: unknown[]
  total?: number
  /** Generates rows from the requested window instead of using `rows`. */
  generate?: number
}

function mockApi({ rows = mixedRows, total, generate }: Setup = {}): string[] {
  const log: string[] = []
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.includes('/files?')) {
      if (generate !== undefined) {
        const params = new URLSearchParams(url.split('?')[1])
        const limit = Number(params.get('limit'))
        const offset = Number(params.get('offset'))
        const count = Math.max(0, Math.min(limit, generate - offset))
        return res(Array.from({ length: count }, (_, i) => file({ id: offset + i + 1, original_filename: `f${offset + i + 1}.mkv` })), generate)
      }
      return res(rows, total ?? rows.length)
    }
    if (url.includes('/shows/5/episodes'))
      return res([
        { id: 50, season_number: 1, episode_number: 2, name: 'Second', file_tracked: true },
        { id: 51, season_number: 1, episode_number: 1, name: 'First', file_tracked: false },
        { id: 60, season_number: 2, episode_number: 1, name: 'Opener', file_tracked: false },
      ])
    return res([], 0)
  })
  return log
}

async function renderPage() {
  render(<Files />, { wrapper: makeWrapper() })
  await screen.findByRole('table')
}

describe('Files characterization', () => {
  test('mixed rows DOM and mount requests', async () => {
    const log = mockApi()
    await renderPage()
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('loading, empty and filtered-empty states', async () => {
    mockApi({ rows: [], total: 0 })
    render(<Files />, { wrapper: makeWrapper() })
    expect(domSnapshot()).toMatchSnapshot('loading')
    await screen.findByText('No files found.')
    expect(domSnapshot()).toMatchSnapshot('empty')
  })

  test('summary line reflects filters and the max-records cap', async () => {
    const log = mockApi({ generate: 120 })
    await renderPage()
    expect(screen.getByText('120 files')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Max records'), { target: { value: '100' } })
    await screen.findByText('100 of 120 files')
    fireEvent.change(screen.getByPlaceholderText('Search filenames…'), { target: { value: 'abc' } })
    await screen.findByText('100 of 120 files matching filters', {}, { timeout: 2000 })
    expect(domSnapshot()).toMatchSnapshot('capped dom')
    expect(log).toMatchSnapshot('requests')
  })

  test('pagination, page reset on filter change and last-page truncation under the cap', async () => {
    const log = mockApi({ generate: 120 })
    await renderPage()
    fireEvent.change(screen.getByLabelText('Per page'), { target: { value: '20' } })
    await screen.findByText('f20.mkv')
    fireEvent.click(screen.getByTitle('Next page'))
    await screen.findByText('f21.mkv')
    fireEvent.change(screen.getByLabelText('Max records'), { target: { value: '50' } })
    await screen.findByText('50 of 120 files')
    fireEvent.click(screen.getByTitle('Next page'))
    fireEvent.click(screen.getByTitle('Next page'))
    await screen.findByText('f50.mkv')
    expect(screen.queryByText('f51.mkv')).toBeNull()
    fireEvent.change(screen.getByDisplayValue('All statuses'), { target: { value: 'error' } })
    await sleep(50)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('show-ignored switch and persisted filters', async () => {
    const log = mockApi()
    await renderPage()
    fireEvent.click(screen.getByRole('switch', { name: 'Show ignored files' }))
    await waitFor(() => expect(log.some((l) => l.includes('show_ignored=true'))).toBe(true))
    expect(domSnapshot()).toMatchSnapshot('dom')
    expect(JSON.parse(window.localStorage.getItem('jidou:files-filters') ?? '{}')).toMatchSnapshot('stored')
  })

  test('inline show id editor: assign, clear, reject, escape', async () => {
    const log = mockApi()
    await renderPage()
    const dashButtons = () => screen.getAllByTitle('Click to assign show')
    fireEvent.click(dashButtons()[0])
    let input = screen.getByRole('spinbutton')
    expect(domSnapshot()).toMatchSnapshot('editing')
    fireEvent.change(input, { target: { value: '77' } })
    fireEvent.blur(input)
    await waitFor(() => expect(log.some((l) => l.startsWith('PATCH'))).toBe(true))
    fireEvent.click(dashButtons()[0])
    input = screen.getByRole('spinbutton')
    fireEvent.change(input, { target: { value: '-3' } })
    fireEvent.blur(input)
    fireEvent.click(dashButtons()[0])
    input = screen.getByRole('spinbutton')
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.blur(input)
    expect(log.filter((l) => !l.startsWith('GET'))).toMatchSnapshot('mutations')
    expect(domSnapshot()).toMatchSnapshot('after')
  })

  test('inline episode picker lists seasons, marks taken, assigns and clears', async () => {
    const log = mockApi()
    await renderPage()
    const pickers = await screen.findAllByTitle('Click to assign episode')
    fireEvent.click(pickers[0])
    await sleep(20)
    expect(domSnapshot()).toMatchSnapshot('picker open')
    const sel = document.querySelector('select[class*="max-w-xs"]') as HTMLSelectElement
    fireEvent.change(sel, { target: { value: '51' } })
    await waitFor(() => expect(log.some((l) => l.startsWith('PATCH'))).toBe(true))
    expect(log.filter((l) => !l.startsWith('GET'))).toMatchSnapshot('mutations')
  })

  test('row actions open their modals', async () => {
    mockApi()
    await renderPage()
    fireEvent.click(screen.getAllByRole('button', { name: 'Resolve' })[0])
    await screen.findByRole('dialog')
    expect(domSnapshot()).toMatchSnapshot('resolve modal')
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    fireEvent.click(screen.getAllByRole('button', { name: 'Fix Show' })[0])
    await screen.findByRole('dialog')
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })
})
