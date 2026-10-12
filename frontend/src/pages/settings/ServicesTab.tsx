import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import type { useAdminHealth, useAdminCache, useFlushCache } from '@/hooks/useAdmin'
import type { ConnectionService, useConnectionTest } from '@/hooks/useSettingsActions'
import type { AppConfig, ConnectionTestResult, ServiceHealth } from '@/types/api'

/** Hook results owned by Settings so their state survives tab switches (as it did before the split). */
export interface ServicesTabProps {
  config: AppConfig | undefined
  cache: ReturnType<typeof useAdminCache>
  flushCache: ReturnType<typeof useFlushCache>
  health: ReturnType<typeof useAdminHealth>
  tests: Record<ConnectionService, ReturnType<typeof useConnectionTest>>
}

/** Service health, on-demand connection tests, TMDB cache and schedules (the Settings "Services" tab). */
export function ServicesTab({ config, cache, flushCache, health: healthQuery, tests }: ServicesTabProps) {
  const { tmdb: testTmdb, sftp: testSftp, redis: testRedis, llm: testLlm } = tests
  const { data: cacheStats, refetch: refetchCache, isFetching: cacheFetching } = cache
  const { data: health, refetch: refetchHealth, isFetching: healthFetching } = healthQuery

  const showLlm = Boolean(config?.llm_provider && config.llm_provider.toLowerCase() !== 'none')

  return (
    <div className="space-y-8">
      {/* Services — health status + on-demand connection tests in one place */}
      <Card padding="md" className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold dark:text-gray-100">Services</h2>
            {health && (
              <span
                className={clsx(
                  'text-xs font-medium px-2 py-0.5 rounded-full',
                  health.healthy ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
                )}
              >
                {health.healthy ? '● Healthy' : '● Degraded'}
              </span>
            )}
            {health && (
              <span className="text-xs text-gray-400 dark:text-gray-500" data-testid="app-version">
                v{health.version}
              </span>
            )}
          </div>
          <button
            onClick={() => refetchHealth()}
            disabled={healthFetching}
            className="px-3 py-1 bg-gray-100 text-sm rounded hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
          >
            {healthFetching ? 'Checking…' : 'Refresh'}
          </button>
        </div>

        <div className="space-y-1.5">
          <ServiceRow
            label="Database"
            svc={health?.services.database}
            test={null}
          />
          <ServiceRow
            label="TMDB"
            svc={health?.services.tmdb}
            test={testTmdb}
          />
          <ServiceRow
            label="SFTP"
            svc={health?.services.sftp}
            test={testSftp}
          />
          <ServiceRow
            label="Redis"
            svc={health?.services.redis}
            test={testRedis}
          />
          <ServiceRow
            label="Celery"
            svc={health?.services.celery}
            test={null}
          />
          {showLlm && (
            <ServiceRow
              label="LLM"
              svc={health?.services.llm}
              test={testLlm}
            />
          )}
        </div>

        {!health && (
          <p className="text-xs text-gray-400 dark:text-gray-500 italic">Click Refresh to check service health</p>
        )}
      </Card>

      <Card padding="md" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold dark:text-gray-100">TMDB Cache</h2>
          <div className="flex gap-2">
            <button
              onClick={() => refetchCache()}
              disabled={cacheFetching}
              className="px-3 py-1 bg-gray-100 text-sm rounded hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
            >
              {cacheFetching ? 'Loading…' : 'Refresh'}
            </button>
            <button
              onClick={() => flushCache.mutate()}
              disabled={flushCache.isPending}
              className="px-3 py-1 bg-orange-100 text-orange-700 text-sm rounded hover:bg-orange-200 disabled:opacity-50 dark:bg-orange-900/40 dark:text-orange-300 dark:hover:bg-orange-900/70"
            >
              {flushCache.isPending ? 'Flushing…' : 'Flush'}
            </button>
          </div>
        </div>
        {cacheStats && (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              {cacheStats.count} / {cacheStats.maxsize} entries · TTL {cacheStats.ttl_seconds}s
            </p>
            {cacheStats.entries.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-gray-500 dark:text-gray-400 mb-1">
                  {cacheStats.entries.length} active {cacheStats.entries.length === 1 ? 'entry' : 'entries'}
                </summary>
                <ul className="mt-1 space-y-0.5 pl-3">
                  {cacheStats.entries.map((entry) => (
                    <li key={entry.key} className="font-mono text-gray-600 dark:text-gray-400 truncate" title={entry.key}>
                      {entry.label}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {cacheStats.entries.length === 0 && (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic">Cache is empty</p>
            )}
          </>
        )}
        {flushCache.data && (
          <p className="text-xs text-gray-500 dark:text-gray-400">Cleared {flushCache.data.cleared} entries</p>
        )}
      </Card>

      {config && (
        <Card padding="md" className="space-y-3">
          <h2 className="font-semibold dark:text-gray-100">Schedules</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            Configured via environment variables; restart required to change. All times UTC.
          </p>
          <div className="space-y-2">
            <ScheduleRow
              label="Full Sync"
              enabled={config.sync_schedule_enabled}
              hours={config.sync_schedule_hours}
            />
            <ScheduleRow
              label="RSS Import"
              enabled={config.rss_import_schedule_enabled}
              hours={config.rss_import_schedule_hours}
            />
          </div>
        </Card>
      )}
    </div>
  )
}

interface TestMutation {
  mutate: () => void
  isPending: boolean
  data?: ConnectionTestResult
}

/** Detail text for a service: latency/revision, model, error or "not configured". */
function baseDetail(svc: ServiceHealth): string {
  if (svc.ok && svc.latency_ms != null) {
    return `${svc.latency_ms} ms${svc.alembic_version ? ` · rev ${svc.alembic_version}` : ''}`
  }
  if (svc.model) return `${svc.provider} / ${svc.model}`
  return svc.error ?? (svc.configured === false ? 'not configured' : '')
}

/**
 * Detail column text. The health check returns no latency_ms for LLM (config-only
 * probe), so the timing from the most recent Test result is surfaced to keep the
 * detail column consistent.
 */
function serviceDetail(svc: ServiceHealth | null | undefined, test: TestMutation | null): string {
  if (!svc) return ''
  const detail = baseDetail(svc)
  if (svc.latency_ms == null && test?.data?.ok && test.data.message) {
    const ms = test.data.message.match(/^(\d+\.?\d*ms)/)?.[1]
    if (ms) return `${ms} · ${detail}`
  }
  return detail
}

/** Check mark, cross or dash for a service's last known state. */
function indicatorFor(ok: boolean | undefined): { color: string; char: string } {
  if (ok === true) return { color: 'text-green-600 dark:text-green-400', char: '✓' }
  if (ok === false) return { color: 'text-red-600 dark:text-red-400', char: '✗' }
  return { color: 'text-gray-300 dark:text-gray-700', char: '–' }
}

/** Result text and Test button for services that support an on-demand check. */
function TestControls({ test }: { test: TestMutation }) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      {/* Result left of button so the button stays anchored to the right */}
      {test.data && (
        <span className={clsx('text-xs', test.data.ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
          {test.data.ok ? 'OK' : test.data.error}
        </span>
      )}
      <button
        onClick={() => test.mutate()}
        disabled={test.isPending}
        className="px-2.5 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
      >
        {test.isPending ? 'Testing…' : 'Test'}
      </button>
    </div>
  )
}

function ServiceRow({
  label,
  svc,
  test,
}: {
  label: string
  svc: ServiceHealth | null | undefined
  test: TestMutation | null
}) {
  // Indicator: prefer health-endpoint data; fall back to most recent test result
  // so services without a health key (e.g. SFTP) still show ✓/✗ after a test.
  const { color, char } = indicatorFor(svc != null ? svc.ok : test?.data?.ok)

  return (
    <div className="flex items-center gap-3 text-sm min-h-[1.75rem]">
      <span className={clsx('w-4 text-center shrink-0 font-medium', color)}>
        {char}
      </span>
      <span className="w-20 text-gray-700 dark:text-gray-300 shrink-0">{label}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400 flex-1">{serviceDetail(svc, test)}</span>
      {test && <TestControls test={test} />}
    </div>
  )
}

function ScheduleRow({ label, enabled, hours }: { label: string; enabled: boolean; hours: string }) {
  const nextRun = enabled ? computeNextRun(hours) : null
  const parsedHours = hours
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)
    .map((h) => `${h.padStart(2, '0')}:00`)
    .join(', ')

  return (
    <div className="flex items-center gap-3 text-sm">
      <span
        className={clsx(
          'text-xs font-medium px-2 py-0.5 rounded-full shrink-0',
          enabled ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
        )}
      >
        {enabled ? 'Enabled' : 'Disabled'}
      </span>
      <span className="w-24 text-gray-700 dark:text-gray-300 shrink-0">{label}</span>
      {enabled ? (
        <>
          <span className="text-xs text-gray-500 dark:text-gray-400 flex-1">Daily at {parsedHours} UTC</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">
            Next: {nextRun ? nextRun.toLocaleString(undefined, { timeZoneName: 'short' }) : '—'}
          </span>
        </>
      ) : (
        <span className="text-xs text-gray-400 dark:text-gray-500 italic flex-1">not scheduled</span>
      )}
    </div>
  )
}

function computeNextRun(hoursStr: string): Date | null {
  const hours = hoursStr
    .split(',')
    .map((h) => parseInt(h.trim(), 10))
    .filter((h) => !isNaN(h) && h >= 0 && h <= 23)
    .sort((a, b) => a - b)
  if (hours.length === 0) return null

  const now = new Date()
  const nowUtcHour = now.getUTCHours()

  const nextHour = hours.find((h) => h > nowUtcHour)
  const next = new Date()
  if (nextHour !== undefined) {
    next.setUTCHours(nextHour, 0, 0, 0)
  } else {
    next.setUTCDate(next.getUTCDate() + 1)
    next.setUTCHours(hours[0], 0, 0, 0)
  }
  return next
}
