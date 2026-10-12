import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { ScanLocalFilesModal } from '@/components/ScanLocalFilesModal'
import type { EpisodeList } from '@/types/api'
import { domSnapshot, mockResponse, sleep } from '../helpers/dom'

/**
 * Characterization of ScanLocalFilesModal: row DOM per scan status and outcome,
 * the proposed-episode seeding and its preservation across Rescan, plain vs
 * replace links, sequential bulk confirm, and per-row failures. Written before
 * the row extraction; it must pass unchanged afterwards.
 */

const originalFetch = globalThis.fetch
let log: string[] = []
let bodies: unknown[] = []
let scanResults: unknown[][] = []
let scanCalls = 0
let failPaths = new Set<string>()
let scanFails = false

const ep = (over: Partial<EpisodeList>): EpisodeList =>
  ({
    id: 10,
    show_id: 1,
    season_number: 1,
    episode_number: 1,
    name: 'Episode',
    file_tracked: false,
    tracked_source: null,
    watched: false,
    backing_files: [],
    tracked_filename_display: null,
    ...over,
  }) as EpisodeList

const episodes = [
  ep({ id: 10, episode_number: 1, name: 'One' }),
  ep({ id: 11, episode_number: 2, name: 'Two', file_tracked: true }),
  ep({ id: 12, episode_number: 3, name: 'Three' }),
  ep({ id: 20, season_number: 2, episode_number: 1, name: 'S2 One' }),
]

const row = (path: string, over: Record<string, unknown> = {}) => ({
  path,
  filename: path.split('/').pop(),
  season: 1,
  episode_number: 1,
  episode: null,
  status: 'unmatched',
  ...over,
})

beforeEach(() => {
  log = []
  bodies = []
  scanResults = []
  scanCalls = 0
  failPaths = new Set()
  scanFails = false
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    log.push(`${init?.method ?? 'GET'} ${url}`)
    if (url.includes('/scan-local-files')) {
      if (scanFails) return mockResponse({ detail: 'scan boom' }, 500)
      const r = scanResults[Math.min(scanCalls, scanResults.length - 1)] ?? []
      scanCalls += 1
      return mockResponse(r)
    }
    if (url.includes('/link-file')) {
      const body = JSON.parse(String(init?.body)) as { path: string }
      bodies.push(body)
      return failPaths.has(body.path) ? mockResponse({ detail: `link boom ${body.path}` }, 422) : mockResponse({ id: 1 })
    }
    if (url.endsWith('/episodes')) return mockResponse(episodes)
    return mockResponse([])
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function renderModal(onClose: () => void = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(createElement(QueryClientProvider, { client: qc }, createElement(ScanLocalFilesModal, { showId: 1, onClose })))
}

const mixed = () => [
  row('/m/a-matched.mkv', { status: 'matched', episode: { id: 10 }, episode_number: 1 }),
  row('/m/b-conflict.mkv', { status: 'conflict', episode: { id: 11 }, episode_number: 2 }),
  row('/m/c-unmatched.mkv', { season: null, episode_number: null }),
  row('/m/d-matched.mkv', { status: 'matched', episode: { id: 12 }, episode_number: 3 }),
]

describe('ScanLocalFilesModal characterization', () => {
  test('scanning, mixed results, and request order', async () => {
    scanResults = [mixed()]
    renderModal()
    expect(domSnapshot()).toMatchSnapshot('scanning')
    await screen.findByText('a-matched.mkv')
    await sleep(20)
    expect(log).toMatchSnapshot('requests')
    expect(domSnapshot()).toMatchSnapshot('results')
  })

  test('empty and failed scans', async () => {
    scanResults = [[]]
    renderModal()
    await screen.findByText(/No new media files/)
    expect(domSnapshot()).toMatchSnapshot('empty')
  })

  test('scan failure message', async () => {
    scanFails = true
    renderModal()
    await screen.findByText('scan boom')
    expect(domSnapshot()).toMatchSnapshot('failed')
  })

  test('selecting a taken episode switches to replace; selecting none disables Link', async () => {
    scanResults = [mixed()]
    renderModal()
    await screen.findByText('c-unmatched.mkv')
    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[2], { target: { value: '11' } })
    expect(domSnapshot()).toMatchSnapshot('replace selected')
    fireEvent.change(selects[2], { target: { value: '' } })
    expect(screen.getAllByRole('button', { name: /^Link/ })[2]).toBeDisabled()
  })

  test('single link, replace link flag, and linked state', async () => {
    scanResults = [mixed()]
    renderModal()
    await screen.findByText('c-unmatched.mkv')
    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[2], { target: { value: '11' } })
    fireEvent.click(screen.getAllByRole('button', { name: /Link/ })[2])
    await waitFor(() => expect(screen.getAllByText('linked').length).toBe(1))
    expect(bodies).toMatchSnapshot('bodies')
    expect(domSnapshot()).toMatchSnapshot('after link')
  })

  test('per-row failure shows its message and the badge; others still link in bulk', async () => {
    scanResults = [mixed()]
    failPaths = new Set(['/m/a-matched.mkv'])
    renderModal()
    await screen.findByText('a-matched.mkv')
    expect(screen.getByRole('button', { name: 'Confirm All Matched (2)' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm All Matched (2)' }))
    await screen.findByText(/link boom/)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm All Matched (1)' })).toBeEnabled())
    expect(bodies).toMatchSnapshot('bodies in order')
    expect(domSnapshot()).toMatchSnapshot('after bulk')
  })

  test('rescan reseeds untouched rows but keeps a manually chosen episode', async () => {
    scanResults = [
      mixed(),
      [
        row('/m/a-matched.mkv', { status: 'matched', episode: { id: 12 } }),
        row('/m/c-unmatched.mkv', { status: 'matched', episode: { id: 10 } }),
      ],
    ]
    renderModal()
    await screen.findByText('c-unmatched.mkv')
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Rescan' }))
    await waitFor(() => expect(screen.getAllByRole('combobox')).toHaveLength(2))
    await sleep(20)
    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('20')
    expect((screen.getAllByRole('combobox')[1] as HTMLSelectElement).value).toBe('10')
    expect(domSnapshot()).toMatchSnapshot('after rescan')
    expect(log.filter((l) => l.includes('scan-local-files'))).toHaveLength(2)
  })

  test('Close button calls onClose', async () => {
    scanResults = [mixed()]
    const onClose = vi.fn()
    renderModal(onClose)
    await screen.findByText('a-matched.mkv')
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })
})
