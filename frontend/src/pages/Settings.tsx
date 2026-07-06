import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { AppConfig, ConnectionTestResult, ServiceHealth, TaskRead } from '@/types/api'
import { useAdminHealth, useAdminCache, useFlushCache } from '@/hooks/useAdmin'
import { useAppSettings, useUpdateAppSettings } from '@/hooks/useSettings'
import clsx from 'clsx'

export default function Settings() {
  const navigate = useNavigate()
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
  })

  const testTmdb = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/tmdb') })
  const testSftp = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/sftp') })
  const testRedis = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/redis') })
  const testLlm = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/llm') })

  const { data: cacheStats, refetch: refetchCache, isFetching: cacheFetching } = useAdminCache()
  const flushCache = useFlushCache()
  const { data: health, refetch: refetchHealth, isFetching: healthFetching } = useAdminHealth()

  const { data: appSettings } = useAppSettings()
  const updateAppSettings = useUpdateAppSettings()

  const seedDryRun = useMutation({
    mutationFn: () => api.post<TaskRead>('/tasks/trigger', { task_type: 'seed', dry_run: true }),
    onSuccess: (task) => navigate(`/tasks?highlight=${task.id}`),
  })
  const seedLive = useMutation({
    mutationFn: () => api.post<TaskRead>('/tasks/trigger', { task_type: 'seed', dry_run: false }),
    onSuccess: (task) => navigate(`/tasks?highlight=${task.id}`),
  })

  const showLlm = Boolean(config?.llm_provider && config.llm_provider.toLowerCase() !== 'none')

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Settings</h1>

      {config && (
        <div className="bg-white rounded-lg shadow p-4 space-y-2">
          <div className="flex items-center justify-between mb-2">
            <h2 className="font-semibold">Configuration</h2>
            <a
              href="/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 bg-indigo-50 text-indigo-600 text-sm rounded border border-indigo-200 hover:bg-indigo-100"
            >
              API Docs →
            </a>
          </div>
          <ConfigRow label="App name" value={config.app_name} />
          <ConfigRow label="Debug" value={String(config.debug)} />
          <ConfigRow label="TMDB API key" value={config.tmdb_api_key_set ? 'Set ✓' : 'Not set ✗'} />
          <div className="flex gap-3 text-sm items-center">
            <span className="text-gray-500 w-32 shrink-0">API auth</span>
            <span
              className={clsx(
                'text-xs font-medium px-2 py-0.5 rounded-full',
                config.api_key_enabled
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-100 text-gray-500',
              )}
            >
              {config.api_key_enabled ? 'Active' : 'Disabled'}
            </span>
          </div>
          <ConfigRow label="LLM provider" value={config.llm_provider} />
          <ConfigRow label="LLM model" value={config.llm_model || 'Not configured'} />
          <ConfigRow label="LLM host" value={config.llm_base_url ?? 'Default'} />
          <ConfigRow label="SFTP host" value={config.sftp_host ?? 'Not configured'} />
          <ConfigRow label="Redis" value={config.redis_url ?? 'Not configured'} />
          <ConfigRow label="Database" value={config.database_url ?? 'Not configured'} />
        </div>
      )}

      {/* Dashboard — user-editable at runtime, unlike the env-backed Configuration card above */}
      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <h2 className="font-semibold">Dashboard</h2>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700">
            Show adult content
            <span className="block text-xs text-gray-400 font-normal">
              Adult-flagged shows and episodes are always tracked; this only controls whether
              they appear in the dashboard's recently-added carousels.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.show_adult_content ?? false}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ show_adult_content: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-indigo-600"
          />
        </label>
      </div>

      {/* Services — health status + on-demand connection tests in one place */}
      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold">Services</h2>
            {health && (
              <span
                className={clsx(
                  'text-xs font-medium px-2 py-0.5 rounded-full',
                  health.healthy ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
                )}
              >
                {health.healthy ? '● Healthy' : '● Degraded'}
              </span>
            )}
          </div>
          <button
            onClick={() => refetchHealth()}
            disabled={healthFetching}
            className="px-3 py-1 bg-gray-100 text-sm rounded hover:bg-gray-200 disabled:opacity-50"
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
            svc={null}
            test={testSftp}
          />
          <ServiceRow
            label="Redis"
            svc={health?.services.redis}
            test={testRedis}
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
          <p className="text-xs text-gray-400 italic">Click Refresh to check service health</p>
        )}
      </div>

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">TMDB Cache</h2>
          <div className="flex gap-2">
            <button
              onClick={() => refetchCache()}
              disabled={cacheFetching}
              className="px-3 py-1 bg-gray-100 text-sm rounded hover:bg-gray-200 disabled:opacity-50"
            >
              {cacheFetching ? 'Loading…' : 'Refresh'}
            </button>
            <button
              onClick={() => flushCache.mutate()}
              disabled={flushCache.isPending}
              className="px-3 py-1 bg-orange-100 text-orange-700 text-sm rounded hover:bg-orange-200 disabled:opacity-50"
            >
              {flushCache.isPending ? 'Flushing…' : 'Flush'}
            </button>
          </div>
        </div>
        {cacheStats && (
          <>
            <p className="text-xs text-gray-500">
              {cacheStats.count} / {cacheStats.maxsize} entries · TTL {cacheStats.ttl_seconds}s
            </p>
            {cacheStats.entries.length > 0 && (
              <details open className="text-xs">
                <summary className="cursor-pointer text-gray-500 mb-1">
                  {cacheStats.entries.length} active {cacheStats.entries.length === 1 ? 'entry' : 'entries'}
                </summary>
                <ul className="mt-1 space-y-0.5 pl-3">
                  {cacheStats.entries.map((entry) => (
                    <li key={entry.key} className="font-mono text-gray-600 truncate" title={entry.key}>
                      {entry.label}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {cacheStats.entries.length === 0 && (
              <p className="text-xs text-gray-400 italic">Cache is empty</p>
            )}
          </>
        )}
        {flushCache.data && (
          <p className="text-xs text-gray-500">Cleared {flushCache.data.cleared} entries</p>
        )}
      </div>

      {config && (
        <div className="bg-white rounded-lg shadow p-4 space-y-3">
          <h2 className="font-semibold">Schedules</h2>
          <p className="text-xs text-gray-500">
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
        </div>
      )}

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <h2 className="font-semibold">SFTP Baseline Files</h2>
        <p className="text-sm text-gray-600">
          Inventories all existing files on the SFTP server and marks them as{' '}
          <span className="font-mono text-xs bg-slate-100 text-slate-600 px-1 rounded">seeded</span>{' '}
          so Jidou will never re-download them. The operation is idempotent — safe to re-run.
        </p>
        <div className="flex gap-3 flex-wrap">
          <button
            onClick={() => seedDryRun.mutate()}
            disabled={seedDryRun.isPending || seedLive.isPending}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100 disabled:opacity-50"
          >
            {seedDryRun.isPending ? 'Running dry run…' : 'Dry Run'}
          </button>
          <button
            onClick={() => {
              if (window.confirm('Mark all current SFTP files as seeded? This cannot be undone without deleting seeded records from the database.')) {
                seedLive.mutate()
              }
            }}
            disabled={seedDryRun.isPending || seedLive.isPending}
            className="px-3 py-1.5 text-sm rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
          >
            {seedLive.isPending ? 'Running…' : 'Run Baseline'}
          </button>
        </div>
        {(seedDryRun.isError || seedLive.isError) && (
          <p className="text-xs text-red-600">
            {String((seedDryRun.error ?? seedLive.error) || 'Unknown error')}
          </p>
        )}
      </div>
    </div>
  )
}

interface TestMutation {
  mutate: () => void
  isPending: boolean
  data?: ConnectionTestResult
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
  let detail = svc
    ? svc.latency_ms != null
      ? `${svc.latency_ms} ms`
      : svc.model
        ? `${svc.provider} / ${svc.model}`
        : svc.error ?? (svc.configured === false ? 'not configured' : '')
    : ''

  // Health check returns no latency_ms for LLM (config-only probe). Surface the
  // timing from the most recent Test result so the detail column stays consistent.
  if (svc && svc.latency_ms == null && test?.data?.ok && test.data.message) {
    const ms = test.data.message.match(/^(\d+\.?\d*ms)/)?.[1]
    if (ms) detail = `${ms} · ${detail}`
  }

  // Indicator: prefer health-endpoint data; fall back to most recent test result
  // so services without a health key (e.g. SFTP) still show ✓/✗ after a test.
  const ok = svc != null ? svc.ok : test?.data?.ok
  const indicatorColor =
    ok === true ? 'text-green-600' : ok === false ? 'text-red-600' : 'text-gray-300'
  const indicatorChar = ok === true ? '✓' : ok === false ? '✗' : '–'

  return (
    <div className="flex items-center gap-3 text-sm min-h-[1.75rem]">
      <span className={clsx('w-4 text-center shrink-0 font-medium', indicatorColor)}>
        {indicatorChar}
      </span>
      <span className="w-20 text-gray-700 shrink-0">{label}</span>
      <span className="text-xs text-gray-500 flex-1">{detail}</span>
      {test && (
        <div className="flex items-center gap-2 shrink-0">
          {/* Result left of button so the button stays anchored to the right */}
          {test.data && (
            <span className={clsx('text-xs', test.data.ok ? 'text-green-600' : 'text-red-600')}>
              {test.data.ok ? 'OK' : test.data.error}
            </span>
          )}
          <button
            onClick={() => test.mutate()}
            disabled={test.isPending}
            className="px-2.5 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
          >
            {test.isPending ? 'Testing…' : 'Test'}
          </button>
        </div>
      )}
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
          enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500',
        )}
      >
        {enabled ? 'Enabled' : 'Disabled'}
      </span>
      <span className="w-24 text-gray-700 shrink-0">{label}</span>
      {enabled ? (
        <>
          <span className="text-xs text-gray-500 flex-1">Daily at {parsedHours} UTC</span>
          <span className="text-xs text-gray-400 shrink-0">
            Next: {nextRun ? nextRun.toLocaleString(undefined, { timeZoneName: 'short' }) : '—'}
          </span>
        </>
      ) : (
        <span className="text-xs text-gray-400 italic flex-1">not scheduled</span>
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

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 w-32 shrink-0">{label}</span>
      <span className="font-mono text-gray-800">{value}</span>
    </div>
  )
}
