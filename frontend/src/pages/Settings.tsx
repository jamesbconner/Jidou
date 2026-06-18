import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AppConfig, ConnectionTestResult } from '@/types/api'
import clsx from 'clsx'

export default function Settings() {
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
  })

  const testTmdb = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/tmdb') })
  const testSftp = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/sftp') })
  const testRedis = useMutation({ mutationFn: () => api.post<ConnectionTestResult>('/config/test/redis') })
  const flushCache = useMutation({ mutationFn: () => api.post<{ ok: boolean; cleared: number }>('/admin/cache/flush') })

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Settings</h1>

      {config && (
        <div className="bg-white rounded-lg shadow p-4 space-y-2">
          <h2 className="font-semibold mb-2">Configuration</h2>
          <ConfigRow label="App name" value={config.app_name} />
          <ConfigRow label="Debug" value={String(config.debug)} />
          <ConfigRow label="TMDB API key" value={config.tmdb_api_key_set ? 'Set ✓' : 'Not set ✗'} />
          <ConfigRow label="LLM provider" value={config.llm_provider} />
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
                  {mutation.data.ok ? 'OK' : mutation.data.error}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-4">
        <h2 className="font-semibold mb-3">Cache</h2>
        <div className="flex items-center gap-3">
          <button
            onClick={() => flushCache.mutate()}
            disabled={flushCache.isPending}
            className="px-3 py-1 bg-orange-100 text-orange-700 text-sm rounded hover:bg-orange-200 disabled:opacity-50"
          >
            Flush TMDB Cache
          </button>
          {flushCache.data && (
            <span className="text-xs text-gray-500">Cleared {flushCache.data.cleared} entries</span>
          )}
        </div>
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
