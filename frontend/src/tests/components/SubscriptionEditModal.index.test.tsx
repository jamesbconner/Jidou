import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi } from 'vitest'
import { createElement } from 'react'
import { http, HttpResponse } from 'msw'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import type { RssFeedRead, RssSubscriptionRead, ShowIndexEntry } from '@/types/api'
import { startMswServer } from '@/tests/helpers/msw'

// DF-18: the "Linked Show" picker searches the lightweight GET /shows/index
// rather than the full /shows list fetched with limit=10000.

function entry(id: number, title: string): ShowIndexEntry {
  return {
    id,
    tmdb_id: 1000 + id,
    title,
    sys_name: title,
    aliases: null,
    media_type: 'tv',
    content_type: null,
    local_path: null,
  }
}

const INDEX = [entry(1, 'Alpha Show'), entry(2, 'Beta Show'), entry(3, 'Gamma Film')]

const { requests } = startMswServer(http.get('/api/shows/index', () => HttpResponse.json(INDEX)))

const feeds = [{ id: 1, name: 'Default Feed' }] as RssFeedRead[]

function sub(overrides: Partial<RssSubscriptionRead> = {}): RssSubscriptionRead {
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
    ...overrides,
  } as unknown as RssSubscriptionRead
}

function renderModal(s: RssSubscriptionRead) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    createElement(
      QueryClientProvider,
      { client: qc },
      createElement(
        MemoryRouter,
        null,
        createElement(SubscriptionEditModal, { sub: s, feeds, onClose: vi.fn() }),
      ),
    ),
  )
}

describe('SubscriptionEditModal — show picker reads /shows/index', () => {
  test('search lists matching index titles and never fetches the full show list', async () => {
    renderModal(sub())

    fireEvent.change(screen.getByPlaceholderText('Search library shows…'), {
      target: { value: 'show' },
    })

    expect(await screen.findByRole('button', { name: 'Alpha Show' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Beta Show' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Gamma Film' })).not.toBeInTheDocument()

    expect(requests).toContain('GET /api/shows/index')
    expect(requests.some((r) => r.startsWith('GET /api/shows?'))).toBe(false)
  })

  test('a linked show resolves its title from the index', async () => {
    renderModal(sub({ show_id: 2 }))

    expect(await screen.findByRole('link', { name: 'Beta Show ↗' })).toBeInTheDocument()
    expect(requests).toContain('GET /api/shows/index')
  })
})
