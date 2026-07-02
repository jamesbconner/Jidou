import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AppConfig, ConnectionTestResult } from '@/types/api'
import { useAdminHealth, useAdminCache, useFlushCache } from '@/hooks/useAdmin'
import clsx from 'clsx'

export default function Settings() {
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
              className="text-xs text-indigo-600 hover:underline"
            >
              API docs →
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

      <div className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-3">Connection Tests</h2>
        <div className="flex flex-wrap gap-3">
          {[
            { label: 'Test TMDB', mutation: testTmdb },
            { label: 'Test SFTP', mutation: testSftp },
            { label: 'Test Redis', mutation: testRedis },
            ...(config?.llm_provider && config.llm_provider.toLowerCase() !== 'none'
              ? [{ label: 'Test LLM', mutation: testLlm }]
              : []),
          ].map(({ label, mutation }) => (
            <div key={label} className="flex items-center gap-2">
              <button
                onClick={() => mutation.mutate()}
                disabled={mutation.isPending}
                className="px-3 py-1 bg-gray-100 text-sm rounded hover:bg-gray-200 disabled:opacity-50"
              >
                {label}
              </button>
              {mutation.data && (
                <span className={clsx('text-xs', mutation.data.ok ? 'text-green-600' : 'text-red-600')}>
                  {mutation.data.ok ? (mutation.data.message ?? 'OK') : mutation.data.error}
                </span>
              )}
            </div>
          ))}
        </div>
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

      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h2 className="font-semibold">System Health</h2>
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
        {health ? (
          <div className="space-y-2">
            {(Object.entries(health.services) as [string, typeof health.services.database][]).map(([name, svc]) => (
              <div key={name} className="flex items-center gap-3 text-sm">
                <span className={clsx('w-4 text-center', svc.ok ? 'text-green-600' : 'text-red-600')}>
                  {svc.ok ? '✓' : '✗'}
                </span>
                <span className="w-20 text-gray-700 capitalize">{name}</span>
                <span className="text-xs text-gray-500">
                  {svc.latency_ms != null
                    ? `${svc.latency_ms} ms`
                    : svc.model
                      ? `${svc.provider} / ${svc.model}`
                      : svc.error ?? (svc.configured === false ? 'not configured' : '')}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-400 italic">Click Refresh to check service health</p>
        )}
      </div>
    </div>
  )
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 w-32 shrink-0">{label}</span>
      <span className="font-mono text-gray-800">{value}</span>
    </div>
  )
}
