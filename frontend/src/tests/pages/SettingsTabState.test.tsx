import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Settings from '@/pages/Settings'

// Guards for state that must outlive a tab switch: the tabs unmount, so the
// hooks behind them have to live in Settings (regression pins for the FE-3 split).

const CONFIG = {
  today: '2026-08-21',
  app_name: 'Jidou',
  debug: false,
  database_url: 'postgresql://localhost/jidou',
  redis_url: 'redis://localhost:6379/0',
  tmdb_api_key_set: true,
  tmdb_base_url: 'https://api.themoviedb.org/3',
  tmdb_rate_limit_per_second: 0.5,
  tmdb_cache_ttl: 604_800,
  sftp_host: 'sftp.example.com',
  sftp_port: 22,
  sftp_username: 'jidou',
  sftp_remote_paths: '/',
  sftp_noscan_paths: '',
  llm_provider: 'none',
  llm_model: '',
  llm_base_url: null,
  llm_cache_ttl: 3600,
  media_paths: {
    tv: { container: '/t', host: '/t' },
    anime: { container: '/a', host: '/a' },
    movie: { container: '/m', host: '/m' },
  },
  image_cache_backend: 'disk',
  image_cache_host_path: '/c',
  image_cache_expiration_enabled: true,
  image_cache_retention_days: 180,
  rss_config_path_set: false,
  api_key_enabled: false,
  sync_schedule_enabled: true,
  sync_schedule_hours: '3',
  rss_import_schedule_enabled: false,
  rss_import_schedule_hours: '',
}

const APP_SETTINGS = {
  show_adult_content: false,
  calendar_enabled: true,
  discover_enabled: true,
  dashboard_page_enabled: true,
  recent_episodes_enabled: true,
  recent_movies_enabled: true,
  recent_episodes_prefer_posters: false,
  similar_titles_enabled: true,
  similar_titles_count: 12,
  similar_titles_include_external: true,
  metadata_refresh_schedule_enabled: true,
  metadata_refresh_schedule_hours: '4',
  metadata_refresh_limit_per_run: 10,
}

function mockResponse(body: unknown = null): Response {
  return { ok: true, status: 200, statusText: '', json: async () => body } as Response
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(MemoryRouter, null, children))
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.endsWith('/api/config')) return mockResponse(CONFIG)
    if (url.endsWith('/api/settings')) return mockResponse(APP_SETTINGS)
    if (url.endsWith('/api/admin/cache')) {
      return mockResponse({ count: 0, maxsize: 100, ttl_seconds: 86400, entries: [] })
    }
    if (url.includes('/api/config/test/')) return mockResponse({ ok: true, message: '5ms round trip' })
    return mockResponse({})
  }) as typeof fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('Settings tab state', () => {
  test('GET /admin/cache fires on initial render, before the Services tab is opened', async () => {
    render(createElement(Settings), { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Application')).toBeInTheDocument())

    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((c) => String(c[0]))
      expect(urls.some((u) => u.endsWith('/api/admin/cache'))).toBe(true)
    })
  })

  test('a connection-test result survives switching to another tab and back', async () => {
    render(createElement(Settings), { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Application')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Services' }))
    const testButtons = await screen.findAllByRole('button', { name: 'Test' })
    expect(testButtons.length).toBeGreaterThanOrEqual(3)
    fireEvent.click(testButtons[0])
    await waitFor(() => expect(screen.getAllByText('OK')).toHaveLength(1))

    fireEvent.click(screen.getByRole('button', { name: 'Features' }))
    expect(screen.queryByText('OK')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Services' }))

    expect(screen.getAllByText('OK')).toHaveLength(1)
  })
})
