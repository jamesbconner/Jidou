import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { ServicesTab, type ServicesTabProps } from '@/pages/settings/ServicesTab'
import { domSnapshot } from '../helpers/dom'

/**
 * Characterization of the Services settings tab: ServiceRow detail text and
 * indicator for every health/test combination, the health header, cache card
 * and schedule rows. Written before the ServiceRow helpers were extracted; it
 * must pass unchanged afterwards.
 */

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-03-04T10:30:00Z'))
  vi.spyOn(Date.prototype, 'toLocaleString').mockImplementation(function (this: Date) {
    return `LOCAL(${this.toISOString()})`
  })
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

type Svc = Record<string, unknown>

const healthy = (services: Record<string, Svc | undefined>, over: Record<string, unknown> = {}) => ({
  healthy: true,
  version: '1.2.3',
  services,
  ...over,
})

interface Mut {
  mutate: ReturnType<typeof vi.fn>
  isPending: boolean
  data?: unknown
}
const mut = (over: Partial<Mut> = {}): Mut => ({ mutate: vi.fn(), isPending: false, ...over })

function setup(over: {
  health?: unknown
  healthFetching?: boolean
  config?: Record<string, unknown> | undefined | null
  cache?: unknown
  cacheFetching?: boolean
  flush?: Partial<Mut>
  tests?: Partial<Record<'tmdb' | 'sftp' | 'redis' | 'llm', Mut>>
} = {}) {
  const refetchHealth = vi.fn()
  const refetchCache = vi.fn()
  const flush = mut(over.flush)
  const tests = {
    tmdb: mut(),
    sftp: mut(),
    redis: mut(),
    llm: mut(),
    ...over.tests,
  }
  const props = {
    config:
      over.config === null
        ? undefined
        : {
            llm_provider: 'ollama',
            sync_schedule_enabled: true,
            sync_schedule_hours: '3, 15,99,x',
            rss_import_schedule_enabled: false,
            rss_import_schedule_hours: '6',
            ...over.config,
          },
    cache: { data: over.cache, refetch: refetchCache, isFetching: over.cacheFetching ?? false },
    flushCache: flush,
    health: { data: over.health, refetch: refetchHealth, isFetching: over.healthFetching ?? false },
    tests,
  } as unknown as ServicesTabProps
  render(<ServicesTab {...props} />)
  return { refetchHealth, refetchCache, flush, tests }
}

describe('ServicesTab characterization: service rows', () => {
  test('no health yet', () => {
    setup()
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('healthy with latency, revision, model, error and unconfigured details', () => {
    setup({
      health: healthy({
        database: { ok: true, latency_ms: 4, alembic_version: 'abc123' },
        tmdb: { ok: true, latency_ms: 120 },
        sftp: { ok: false, error: 'connection refused' },
        redis: { ok: false, configured: false },
        celery: { ok: false },
        llm: { ok: true, provider: 'ollama', model: 'llama3' },
      }),
    })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('degraded header and checking state', () => {
    setup({ health: healthy({ database: { ok: false, error: 'down' } }, { healthy: false }), healthFetching: true })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('latency from the last LLM test is prepended when health has none', () => {
    setup({
      health: healthy({ llm: { ok: true, provider: 'ollama', model: 'llama3' } }),
      tests: { llm: mut({ data: { ok: true, message: '42.5ms round trip' } }) },
    })
    expect(domSnapshot()).toMatchSnapshot('with ms')
  })

  test('test message without a leading timing is ignored', () => {
    setup({
      health: healthy({ llm: { ok: true, provider: 'ollama', model: 'llama3' } }),
      tests: { llm: mut({ data: { ok: true, message: 'fine' } }) },
    })
    expect(domSnapshot()).toMatchSnapshot('no ms')
  })

  test('indicator falls back to the test result when health has no entry', () => {
    setup({
      health: healthy({}),
      tests: {
        sftp: mut({ data: { ok: true } }),
        redis: mut({ data: { ok: false, error: 'nope' } }),
        tmdb: mut({ isPending: true }),
      },
    })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('LLM row hidden when provider is none or missing', () => {
    setup({ config: { llm_provider: 'None' }, health: healthy({}) })
    expect(screen.queryByText('LLM')).toBeNull()
    expect(domSnapshot()).toMatchSnapshot('provider none')
  })

  test('buttons call their handlers', () => {
    const { refetchHealth, tests } = setup({ health: healthy({}) })
    fireEvent.click(screen.getAllByRole('button', { name: 'Refresh' })[0])
    expect(refetchHealth).toHaveBeenCalledTimes(1)
    const testButtons = screen.getAllByRole('button', { name: 'Test' })
    expect(testButtons).toHaveLength(4)
    for (const b of testButtons) fireEvent.click(b)
    expect(tests.tmdb.mutate).toHaveBeenCalledTimes(1)
    expect(tests.sftp.mutate).toHaveBeenCalledTimes(1)
    expect(tests.redis.mutate).toHaveBeenCalledTimes(1)
    expect(tests.llm.mutate).toHaveBeenCalledTimes(1)
  })
})

describe('ServicesTab characterization: cache and schedules', () => {
  test('cache card with entries, flush result and fetching state', () => {
    setup({
      cache: { count: 2, maxsize: 100, ttl_seconds: 86400, entries: [{ key: 'k1', label: 'One' }, { key: 'k2', label: 'Two' }] },
      flush: { data: { cleared: 7 } },
      cacheFetching: true,
    })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('cache with a single entry, an empty cache and a pending flush', () => {
    const { flush } = setup({
      cache: { count: 1, maxsize: 100, ttl_seconds: 5, entries: [{ key: 'k1', label: 'One' }] },
      flush: { isPending: true },
    })
    expect(domSnapshot()).toMatchSnapshot('single')
    void flush
  })

  test('empty cache', () => {
    setup({ cache: { count: 0, maxsize: 100, ttl_seconds: 5, entries: [] } })
    expect(domSnapshot()).toMatchSnapshot('empty')
  })

  test('schedule rows: enabled with next run, disabled, and the wrap to tomorrow', () => {
    setup({
      config: { sync_schedule_hours: '3,15', rss_import_schedule_enabled: true, rss_import_schedule_hours: '1,2' },
    })
    expect(domSnapshot()).toMatchSnapshot('dom')
  })

  test('schedule row with no valid hours shows an em dash; no config hides schedules', () => {
    setup({ config: { sync_schedule_hours: 'x' } })
    expect(domSnapshot()).toMatchSnapshot('no valid hours')
  })

  test('no config at all', () => {
    setup({ config: null })
    expect(domSnapshot()).toMatchSnapshot('no config')
  })
})
