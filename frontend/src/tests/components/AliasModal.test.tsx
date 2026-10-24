import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { AliasModal } from '@/components/AliasModal'
import type { ShowRead } from '@/types/api'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// See Watchlist.test.tsx for why a plain assignment (not vi.spyOn) is used here.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: '',
    json: async () => ({}),
  } as Response)
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

function makeShow(overrides: Partial<ShowRead> = {}): ShowRead {
  return {
    id: 1,
    tmdb_id: 100,
    title: 'Example Show',
    media_type: 'tv',
    vote_count: 0,
    cached: false,
    aliases_sources: { tmdb: [], llm: [], user: [] },
    season_aliases: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as ShowRead
}

function seasonAliasesPut(): unknown {
  const call = vi
    .mocked(globalThis.fetch)
    .mock.calls.find(([url]) => url === '/api/shows/1/season-aliases')
  expect(call).toBeDefined()
  expect((call![1] as RequestInit).method).toBe('PUT')
  return JSON.parse((call![1] as RequestInit).body as string)
}

describe('AliasModal season names', () => {
  test('lists the show’s existing season names', () => {
    render(
      <AliasModal show={makeShow({ season_aliases: { 'example arc-hen': 2 } })} onClose={vi.fn()} />,
      { wrapper: makeWrapper() },
    )

    expect(screen.getByText('example arc-hen')).toBeInTheDocument()
    expect(screen.getByText('Season 2')).toBeInTheDocument()
  })

  test('adding a season name and saving sends the whole map', async () => {
    render(<AliasModal show={makeShow()} onClose={vi.fn()} />, { wrapper: makeWrapper() })

    fireEvent.change(screen.getByPlaceholderText('Add season name…'), {
      target: { value: 'Example Arc-hen' },
    })
    fireEvent.change(screen.getByLabelText('Season number'), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add season name' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(seasonAliasesPut()).toEqual({ season_aliases: { 'example arc-hen': 2 } }),
    )
  })

  test('removing a season name and saving sends the map without it', async () => {
    render(
      <AliasModal
        show={makeShow({ season_aliases: { 'example arc-hen': 2, 'other arc': 3 } })}
        onClose={vi.fn()}
      />,
      { wrapper: makeWrapper() },
    )

    fireEvent.click(screen.getByRole('button', { name: 'Remove season name other arc' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(seasonAliasesPut()).toEqual({ season_aliases: { 'example arc-hen': 2 } }),
    )
  })
})
