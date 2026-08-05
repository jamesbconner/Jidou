import { useRef, useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import type { AppConfig, ConnectionTestResult, ServiceHealth, TaskRead } from '@/types/api'
import { useAdminHealth, useAdminCache, useFlushCache } from '@/hooks/useAdmin'
import { useAppSettings, useUpdateAppSettings } from '@/hooks/useSettings'
import { useImportText, useExportDatabase, useImportDatabase } from '@/hooks/useData'
import { useTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import clsx from 'clsx'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'

type Tab = 'general' | 'data'

// ---------------------------------------------------------------------------
// Live task tracker — subscribes to WS progress for a single task
// ---------------------------------------------------------------------------

function LiveImportTask({ task }: { task: TaskRead }) {
  const { data: live } = useTask(task.id)
  useTaskProgress(task.celery_task_id)
  const t = live ?? task
  return (
    <div className="mt-4 space-y-2">
      <TaskProgressBar task={t} />
      {t.status === 'completed' && t.result_summary && (
        <pre className="text-xs bg-gray-50 border rounded p-2 overflow-x-auto">
          {JSON.stringify(t.result_summary, null, 2)}
        </pre>
      )}
      {t.status === 'failed' && (
        <p className="text-sm text-red-600">{t.progress_message}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Text File Import section
// ---------------------------------------------------------------------------

type ImportMode = 'full' | 'shows_only' | 'episodes_only'

const IMPORT_MODE_OPTIONS: { value: ImportMode; label: string; description: string }[] = [
  {
    value: 'full',
    label: 'Full',
    description: 'Create/find shows and match episodes in one pass (default). Each line' +
      'should represent the full path of an episode file.',
  },
  {
    value: 'shows_only',
    label: 'Shows only',
    description:
      'Create/find shows and sync their episodes, but skip episode matching. Useful as a ' +
      'first pass to populate or verify the show catalog before touching episode-level data. ' +
      'Each line can be the path to a bare show directory instead of a full episode file path.',
  },
  {
    value: 'episodes_only',
    label: 'Episodes only',
    description:
      'Match episodes only against shows already in the database. Never searches TMDB or ' +
      'creates a new show. Files under a show not already in the database are reported ' +
      'unmatched.',
  },
]

function TextImportSection() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [contentType, setContentType] = useState('anime')
  const [dryRun, setDryRun] = useState(false)
  const [mode, setMode] = useState<ImportMode>('full')
  const [task, setTask] = useState<TaskRead | null>(null)
  const { mutate, isPending, error } = useImportText()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setTask(null)
    mutate(
      { file, contentType, dryRun, mode },
      {
        onSuccess: (t) => setTask(t),
      },
    )
  }

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Text File Import</h2>
        <p className="text-sm text-gray-500 mt-1">
          Upload a plain-text file of episode paths (one per line) to batch-import shows and mark
          episodes as tracked. Accepts Windows and Linux paths.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-xs text-gray-500 mb-1">Import mode</legend>
          {IMPORT_MODE_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-start gap-2 text-sm cursor-pointer">
              <input
                type="radio"
                name="import-mode"
                value={opt.value}
                checked={mode === opt.value}
                onChange={() => setMode(opt.value)}
                className="mt-0.5"
              />
              <span>
                <span className="font-medium">{opt.label}</span>
                <span className="text-gray-500"> — {opt.description}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Path file (.txt)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,text/plain"
              required
              className="text-sm"
            />
          </div>

          <div>
            <label className="text-xs text-gray-500 block mb-1">Content type</label>
            <select
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              title="Selects which library root anchors path parsing — required in every mode, not just for newly created shows"
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="anime">Anime</option>
              <option value="tv">TV</option>
              <option value="movie">Movie</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded"
            />
            Dry run
          </label>

          <Button type="submit" disabled={isPending} variant="primary" tone="light" size="md">
            {isPending ? 'Submitting…' : 'Import'}
          </Button>
        </div>

        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Database Export section
// ---------------------------------------------------------------------------

function DatabaseExportSection() {
  const { mutate, isPending, error, isSuccess } = useExportDatabase()

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Database Export</h2>
        <p className="text-sm text-gray-500 mt-1">
          Download all shows, episodes, and watchlist entries as a JSON backup file.
        </p>
      </div>

      <button
        onClick={() => mutate()}
        disabled={isPending}
        className="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
      >
        {isPending ? 'Preparing…' : 'Download backup'}
      </button>

      {isSuccess && (
        <p className="text-sm text-green-700">Download started.</p>
      )}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Database Import section
// ---------------------------------------------------------------------------

function DatabaseImportSection() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [task, setTask] = useState<TaskRead | null>(null)
  const { mutate, isPending, error } = useImportDatabase()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const file = fileRef.current?.files?.[0]
    if (!file) return
    setTask(null)
    mutate(file, { onSuccess: (t) => setTask(t) })
  }

  return (
    <Card as="section" padding="lg" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Database Import</h2>
        <p className="text-sm text-gray-500 mt-1">
          Restore from a Jidou backup JSON file. Shows and episodes are upserted by TMDB ID;
          existing local paths are preserved when absent in the backup.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="flex flex-wrap gap-4 items-end">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Backup file (.json)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              required
              className="text-sm"
            />
          </div>

          <Button type="submit" disabled={isPending} variant="primary" tone="light" size="md">
            {isPending ? 'Submitting…' : 'Restore'}
          </Button>
        </div>

        {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
        {task && <LiveImportTask task={task} />}
      </form>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Settings() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('general')

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

  const backfillDryRun = useMutation({
    mutationFn: () =>
      api.post<TaskRead>('/tasks/trigger', { task_type: 'backfill_show_metadata', dry_run: true }),
    onSuccess: (task) => navigate(`/tasks?highlight=${task.id}`),
  })
  const backfillLive = useMutation({
    mutationFn: () =>
      api.post<TaskRead>('/tasks/trigger', { task_type: 'backfill_show_metadata', dry_run: false }),
    onSuccess: (task) => navigate(`/tasks?highlight=${task.id}`),
  })

  const showLlm = Boolean(config?.llm_provider && config.llm_provider.toLowerCase() !== 'none')

  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? 'border-blue-600 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700'
    }`

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>

      {/* Tabs */}
      <div className="flex border-b">
        <button className={tabCls('general')} onClick={() => setTab('general')}>
          General
        </button>
        <button className={tabCls('data')} onClick={() => setTab('data')}>
          Data
        </button>
      </div>

      {tab === 'general' && (
        <div className="space-y-8">
          {config && (
            <Card padding="md" className="space-y-2">
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
            </Card>
          )}

          {/* Dashboard — user-editable at runtime, unlike the env-backed Configuration card above */}
          <Card padding="md" className="space-y-3">
            <h2 className="font-semibold">Dashboard</h2>
            <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
              <span className="text-gray-700">
                Show adult content
                <span className="block text-xs text-gray-400 font-normal">
                  Adult-flagged shows and episodes are always tracked; this only controls whether
                  they appear in the dashboard&apos;s recently-added carousels.
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
            <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
              <span className="text-gray-700">
                Calendar
                <span className="block text-xs text-gray-400 font-normal">
                  Show the airing calendar page and its nav link.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={appSettings?.calendar_enabled ?? true}
                disabled={!appSettings || updateAppSettings.isPending}
                onChange={(e) =>
                  updateAppSettings.mutate({ calendar_enabled: e.target.checked })
                }
                className="h-4 w-4 shrink-0 accent-indigo-600"
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
              <span className="text-gray-700">
                Discover
                <span className="block text-xs text-gray-400 font-normal">
                  Show the discover page and its nav link.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={appSettings?.discover_enabled ?? true}
                disabled={!appSettings || updateAppSettings.isPending}
                onChange={(e) =>
                  updateAppSettings.mutate({ discover_enabled: e.target.checked })
                }
                className="h-4 w-4 shrink-0 accent-indigo-600"
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
              <span className="text-gray-700">
                Recently added episodes
                <span className="block text-xs text-gray-400 font-normal">
                  Show the &quot;Recently Added Episodes&quot; carousel on the dashboard.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={appSettings?.recent_episodes_enabled ?? true}
                disabled={!appSettings || updateAppSettings.isPending}
                onChange={(e) =>
                  updateAppSettings.mutate({ recent_episodes_enabled: e.target.checked })
                }
                className="h-4 w-4 shrink-0 accent-indigo-600"
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
              <span className="text-gray-700">
                Recently added movies
                <span className="block text-xs text-gray-400 font-normal">
                  Show the &quot;Recently Added Movies&quot; carousel on the dashboard.
                </span>
              </span>
              <input
                type="checkbox"
                role="switch"
                checked={appSettings?.recent_movies_enabled ?? true}
                disabled={!appSettings || updateAppSettings.isPending}
                onChange={(e) =>
                  updateAppSettings.mutate({ recent_movies_enabled: e.target.checked })
                }
                className="h-4 w-4 shrink-0 accent-indigo-600"
              />
            </label>
          </Card>

          {/* Services — health status + on-demand connection tests in one place */}
          <Card padding="md" className="space-y-3">
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
          </Card>

          <Card padding="md" className="space-y-3">
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
          </Card>

          {config && (
            <Card padding="md" className="space-y-3">
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
            </Card>
          )}
        </div>
      )}

      {tab === 'data' && (
        <div className="space-y-6">
          <TextImportSection />
          <DatabaseExportSection />
          <DatabaseImportSection />

          <Card padding="md" className="space-y-3">
            <h2 className="font-semibold">SFTP Baseline Files</h2>
            <p className="text-sm text-gray-600">
              Inventories all existing files on the SFTP server and marks them as{' '}
              <span className="font-mono text-xs bg-slate-100 text-slate-600 px-1 rounded">seeded</span>{' '}
              so Jidou will never re-download them. The operation is idempotent — safe to re-run.
            </p>
            <div className="flex gap-3 flex-wrap">
              <Button onClick={() => seedDryRun.mutate()} disabled={seedDryRun.isPending || seedLive.isPending} variant="secondary" tone="light" size="md">
                {seedDryRun.isPending ? 'Running dry run…' : 'Dry Run'}
              </Button>
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
          </Card>

          <Card padding="md" className="space-y-3">
            <h2 className="font-semibold">Show Metadata Backfill</h2>
            <p className="text-sm text-gray-600">
              Refetches full TMDB details for shows with no genre data (e.g. added by searching TMDB
              directly rather than resolving a matched file) and reapplies genres, external IDs, and
              other TMDB fields. Local path, content type, aliases, and folder naming are never
              touched. Safe to re-run.
            </p>
            <div className="flex gap-3 flex-wrap">
              <Button onClick={() => backfillDryRun.mutate()} disabled={backfillDryRun.isPending || backfillLive.isPending} variant="secondary" tone="light" size="md">
                {backfillDryRun.isPending ? 'Running dry run…' : 'Dry Run'}
              </Button>
              <button
                onClick={() => {
                  if (window.confirm('Backfill missing TMDB metadata for all affected shows?')) {
                    backfillLive.mutate()
                  }
                }}
                disabled={backfillDryRun.isPending || backfillLive.isPending}
                className="px-3 py-1.5 text-sm rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
              >
                {backfillLive.isPending ? 'Running…' : 'Run Backfill'}
              </button>
            </div>
            {(backfillDryRun.isError || backfillLive.isError) && (
              <p className="text-xs text-red-600">
                {String((backfillDryRun.error ?? backfillLive.error) || 'Unknown error')}
              </p>
            )}
          </Card>
        </div>
      )}
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
