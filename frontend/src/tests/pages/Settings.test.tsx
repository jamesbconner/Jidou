import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import Settings from '@/pages/Settings'
import type { AppConfig, AppSettings, CacheStats, HealthCheck } from '@/types/api'

function makeConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    today: '2026-08-21',
    app_name: 'Jidou',
    debug: false,
    database_url: 'postgresql://localhost/jidou',
    redis_url: 'redis://localhost:6379/0',
    tmdb_api_key_set: true,
    tmdb_base_url: 'https://api.themoviedb.org/3',
    sftp_host: 'sftp.example.com',
    sftp_port: 22,
    sftp_username: 'jidou',
    llm_provider: 'none',
    llm_model: '',
    llm_base_url: null,
    media_paths: {} as AppConfig['media_paths'],
    rss_config_path_set: false,
    api_key_enabled: false,
    sync_schedule_enabled: true,
    sync_schedule_hours: '3',
    rss_import_schedule_enabled: false,
    rss_import_schedule_hours: '',
    ...overrides,
  }
}

function makeAppSettings(overrides: Partial<AppSettings> = {}): AppSettings {
  return {
    show_adult_content: false,
    calendar_enabled: true,
    discover_enabled: true,
    recent_episodes_enabled: true,
    recent_movies_enabled: true,
    recent_episodes_prefer_posters: false,
    ...overrides,
  }
}

function makeCacheStats(overrides: Partial<CacheStats> = {}): CacheStats {
  return { count: 0, maxsize: 100, ttl_seconds: 86400, entries: [], ...overrides }
}

function makeHealth(overrides: Partial<HealthCheck> = {}): HealthCheck {
  return {
    healthy: true,
    services: {
      database: { ok: true, latency_ms: 4.2, alembic_version: 'abc123def456' },
      redis: { ok: true, latency_ms: 1.1 },
      celery: { ok: true, latency_ms: 12.5, workers: ['worker1@host'] },
      tmdb: { ok: true, configured: true },
      sftp: { ok: true, configured: true },
      llm: { ok: true, configured: false },
    },
    ...overrides,
  }
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(MemoryRouter, null, children))
}

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

function mockResponse(body: unknown = null, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: '',
    json: async () => body,
  } as Response
}

function setupFetch(options: {
  config?: AppConfig
  appSettings?: AppSettings
  cache?: CacheStats
  health?: HealthCheck
} = {}) {
  const config = options.config ?? makeConfig()
  const appSettings = options.appSettings ?? makeAppSettings()
  const cache = options.cache ?? makeCacheStats()
  const health = options.health ?? makeHealth()

  vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'

    if (url.endsWith('/api/config')) return mockResponse(config)
    if (url.endsWith('/api/settings')) return mockResponse(appSettings)
    if (url.endsWith('/api/admin/cache')) return mockResponse(cache)
    if (url.endsWith('/api/admin/health')) return mockResponse(health)
    if (method === 'POST' && url.endsWith('/api/config/test/tmdb')) {
      return mockResponse({ ok: true, message: '120ms round trip' })
    }
    if (method === 'POST' && url.endsWith('/api/config/test/sftp')) {
      return mockResponse({ ok: true, message: '80ms round trip' })
    }
    if (method === 'POST' && url.endsWith('/api/config/test/redis')) {
      return mockResponse({ ok: true, message: '5ms round trip' })
    }
    return mockResponse(null)
  })
}

describe('Settings page — Services panel', () => {
  test('Database row shows a dash indicator and no detail before Refresh is clicked', async () => {
    setupFetch()
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Database')).toBeInTheDocument())
    expect(screen.getByText('Click Refresh to check service health')).toBeInTheDocument()
  })

  test('clicking Refresh surfaces the alembic revision on the Database row', async () => {
    setupFetch()
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Database')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))

    await waitFor(() => {
      expect(screen.getByText('4.2 ms · rev abc123def456')).toBeInTheDocument()
    })
    expect(screen.queryByText('Click Refresh to check service health')).not.toBeInTheDocument()
  })

  test('Database row omits the revision suffix when alembic_version is null', async () => {
    setupFetch({
      health: makeHealth({
        services: {
          ...makeHealth().services,
          database: { ok: true, latency_ms: 4.2, alembic_version: null },
        },
      }),
    })
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Database')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))

    await waitFor(() => {
      expect(screen.getByText('4.2 ms')).toBeInTheDocument()
    })
    expect(screen.queryByText(/rev /)).not.toBeInTheDocument()
  })

  test('overall Degraded badge and per-service failure surface when the database check fails', async () => {
    setupFetch({
      health: makeHealth({
        healthy: false,
        services: {
          ...makeHealth().services,
          database: { ok: false, latency_ms: 3.0, error: 'connection refused' },
        },
      }),
    })
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Database')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /refresh/i }))

    await waitFor(() => {
      expect(screen.getByText('● Degraded')).toBeInTheDocument()
    })
    expect(screen.getByText('connection refused')).toBeInTheDocument()
  })

  test('TMDB Test button runs an on-demand connection test independent of the health refresh', async () => {
    setupFetch()
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('TMDB')).toBeInTheDocument())
    const testButtons = screen.getAllByRole('button', { name: 'Test' })
    fireEvent.click(testButtons[0])

    await waitFor(() => {
      expect(screen.getByText('OK')).toBeInTheDocument()
    })
  })
})

describe('Settings page — tabs', () => {
  test('Data tab renders the import/export sections', async () => {
    setupFetch()
    render(createElement(Settings), { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Configuration')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Data' }))

    expect(screen.getByText('Text File Import')).toBeInTheDocument()
    expect(screen.getByText('Database Export')).toBeInTheDocument()
    expect(screen.getByText('Database Import')).toBeInTheDocument()
  })
})
