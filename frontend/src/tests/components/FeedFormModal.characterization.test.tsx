import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { FeedFormModal } from '@/components/FeedFormModal'
import type { RssFeedRead } from '@/types/api'
import { domSnapshot, mockResponse } from '../helpers/dom'

/**
 * Characterization of FeedFormModal: create and edit DOM, the exclude-hint
 * tri-state (blank / text / "no exclude needed"), sample editing, the exact
 * create/patch payloads with trimming, and the pending/disabled states. Written
 * before the draft helpers were extracted; it must pass unchanged afterwards.
 */

const originalFetch = globalThis.fetch
let calls: { method: string; url: string; body: unknown }[] = []
let responder: () => Response

beforeEach(() => {
  calls = []
  responder = () => mockResponse({})
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ method: init?.method ?? 'GET', url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null })
    return responder()
  }) as typeof fetch
})
afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

const feed = (over: Record<string, unknown> = {}): RssFeedRead =>
  ({
    id: 4,
    remote_key: '2',
    name: 'Feed',
    url: 'https://example.com/feed',
    default_download_location: '/dl',
    default_move_completed: '/done',
    active: false,
    regex_include_samples: [
      { sample_name: 'A.S01E01', hint: '^A.*' },
      { sample_name: 'B', hint: 'b' },
    ],
    regex_exclude_hint: 'x264',
    extra_config: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...over,
  }) as RssFeedRead

function renderModal(f: RssFeedRead | null, onClose: () => void = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(createElement(QueryClientProvider, { client: qc }, createElement(FeedFormModal, { feed: f, onClose })))
  return onClose
}

describe('FeedFormModal characterization', () => {
  test('create DOM', () => {
    renderModal(null)
    expect(domSnapshot()).toMatchSnapshot('dom')
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled()
  })

  test('edit DOM with samples and an exclude hint', () => {
    renderModal(feed())
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('edit DOM where a blank exclude hint means "no exclude needed"', () => {
    renderModal(feed({ regex_exclude_hint: '', regex_include_samples: null, active: true }))
    expect(domSnapshot()).toMatchSnapshot('dom')
    expect(screen.getByPlaceholderText(/spanish/)).toBeDisabled()
  })

  test('null exclude hint leaves the checkbox off', () => {
    renderModal(feed({ regex_exclude_hint: null }))
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('add, edit and remove samples; add button disappears at three', () => {
    renderModal(feed({ regex_include_samples: [] }))
    const add = () => screen.getByRole('button', { name: '+ Add sample' })
    fireEvent.click(add())
    fireEvent.click(add())
    fireEvent.click(add())
    expect(screen.queryByRole('button', { name: '+ Add sample' })).toBeNull()
    fireEvent.change(screen.getAllByPlaceholderText(/Sample name/)[1], { target: { value: 'N' } })
    fireEvent.change(screen.getAllByPlaceholderText(/Hint/)[1], { target: { value: 'H' } })
    expect(domSnapshot()).toMatchSnapshot('three samples')
    fireEvent.click(screen.getByRole('button', { name: 'Remove sample 1' }))
    expect(domSnapshot()).toMatchSnapshot('after remove')
  })

  test('create sends trimmed fields, null for blanks, and closes', async () => {
    const onClose = renderModal(null)
    const inputs = screen.getAllByRole('textbox')
    fireEvent.change(screen.getByPlaceholderText('e.g. ShowRSS'), { target: { value: '  Name  ' } })
    fireEvent.change(screen.getByPlaceholderText('https://…'), { target: { value: ' https://x.example ' } })
    fireEvent.change(screen.getByPlaceholderText('e.g. 1'), { target: { value: '  ' } })
    void inputs
    fireEvent.click(screen.getByRole('button', { name: '+ Add sample' }))
    fireEvent.change(screen.getByPlaceholderText(/Sample name/), { target: { value: ' S ' } })
    fireEvent.change(screen.getByPlaceholderText(/Hint/), { target: { value: ' H ' } })
    fireEvent.change(screen.getByPlaceholderText(/spanish/), { target: { value: '  ex  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toMatchSnapshot('calls')
  })

  test('create with no exclude needed sends an empty-string hint; empty samples send null', async () => {
    const onClose = renderModal(null)
    fireEvent.change(screen.getByPlaceholderText('e.g. ShowRSS'), { target: { value: 'N' } })
    fireEvent.change(screen.getByPlaceholderText('https://…'), { target: { value: 'u' } })
    fireEvent.change(screen.getByPlaceholderText(/spanish/), { target: { value: 'ignored' } })
    fireEvent.click(screen.getByLabelText(/don't need an exclude filter/))
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toMatchSnapshot('calls')
  })

  test('create with a blank exclude hint sends null', async () => {
    const onClose = renderModal(null)
    fireEvent.change(screen.getByPlaceholderText('e.g. ShowRSS'), { target: { value: 'N' } })
    fireEvent.change(screen.getByPlaceholderText('https://…'), { target: { value: 'u' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toMatchSnapshot('calls')
  })

  test('edit patches the feed; toggling active and dropping blank-hint samples', async () => {
    const onClose = renderModal(feed())
    fireEvent.click(screen.getByLabelText(/Active \(included/))
    fireEvent.change(screen.getAllByPlaceholderText(/Hint/)[1], { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(calls).toMatchSnapshot('calls')
  })

  test('blank required fields disable save and saving does nothing', () => {
    renderModal(feed())
    fireEvent.change(screen.getByPlaceholderText('e.g. ShowRSS'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(calls).toHaveLength(0)
  })

  test('pending state shows Saving…', async () => {
    responder = () => new Promise(() => {}) as unknown as Response
    renderModal(feed())
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByRole('button', { name: 'Saving…' })
    expect(domSnapshot()).toMatchSnapshot('pending')
  })
})
