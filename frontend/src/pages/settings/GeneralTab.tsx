import clsx from 'clsx'
import { Card } from '@/components/ui/Card'
import type { AppConfig } from '@/types/api'
import { ConfigRow, PathRow } from './rows'

/** Read-only view of the backend configuration (the Settings "General" tab). */
export function GeneralTab({ config }: { config: AppConfig }) {
  return (
    <div className="space-y-8">
      <Card padding="md" className="space-y-2">
        <div className="flex items-center justify-between mb-2">
          <h2 className="font-semibold dark:text-gray-100">Application</h2>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1 bg-[var(--color-ocean-50)] text-[var(--color-ocean-600)] text-sm rounded border border-[var(--color-ocean-200)] hover:bg-[var(--color-ocean-100)] dark:bg-[var(--color-ocean-950)]/40 dark:text-[var(--color-ocean-300)] dark:border-[var(--color-ocean-800)] dark:hover:bg-[var(--color-ocean-900)]/40"
          >
            API Docs →
          </a>
        </div>
        <ConfigRow label="App name" value={config.app_name} />
        <ConfigRow label="Debug" value={String(config.debug)} />
        <div className="flex gap-3 text-sm items-center">
          <span className="text-gray-500 dark:text-gray-400 w-32 shrink-0">API auth</span>
          <span
            className={clsx(
              'text-xs font-medium px-2 py-0.5 rounded-full',
              config.api_key_enabled
                ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300'
                : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
            )}
          >
            {config.api_key_enabled ? 'Active' : 'Disabled'}
          </span>
        </div>
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">Database</h2>
        <ConfigRow label="Connection" value={config.database_url ?? 'Not configured'} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">Redis</h2>
        <ConfigRow label="Connection" value={config.redis_url ?? 'Not configured'} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">TMDB</h2>
        <ConfigRow label="API key" value={config.tmdb_api_key_set ? 'Set ✓' : 'Not set ✗'} />
        <ConfigRow label="Base URL" value={config.tmdb_base_url} />
        <ConfigRow label="Rate limit" value={`${config.tmdb_rate_limit_per_second} req/s`} />
        <ConfigRow label="Cache TTL" value={`${config.tmdb_cache_ttl}s`} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">LLM</h2>
        <ConfigRow label="Provider" value={config.llm_provider} />
        <ConfigRow label="Model" value={config.llm_model || 'Not configured'} />
        <ConfigRow label="Host" value={config.llm_base_url ?? 'Default'} />
        <ConfigRow label="Cache TTL" value={`${config.llm_cache_ttl}s`} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">SFTP</h2>
        <ConfigRow label="Host" value={config.sftp_host ?? 'Not configured'} />
        <ConfigRow label="Port" value={String(config.sftp_port)} />
        <ConfigRow label="Username" value={config.sftp_username ?? 'Not configured'} />
        <ConfigRow label="Remote paths" value={config.sftp_remote_paths} />
        <ConfigRow label="Noscan paths" value={config.sftp_noscan_paths || 'None'} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">Media Paths</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Host-side paths are shown for reference; Jidou reads/writes the container path.
        </p>
        <PathRow label="TV" entry={config.media_paths.tv} />
        <PathRow label="Anime" entry={config.media_paths.anime} />
        <PathRow label="Movie" entry={config.media_paths.movie} />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="font-semibold dark:text-gray-100">Image Cache</h2>
        <ConfigRow label="Backend" value={config.image_cache_backend} />
        <ConfigRow label="Host path" value={config.image_cache_host_path} />
        <ConfigRow
          label="Expiration"
          value={
            config.image_cache_expiration_enabled
              ? `Enabled — ${config.image_cache_retention_days}d retention`
              : 'Disabled (kept indefinitely)'
          }
        />
      </Card>
    </div>
  )
}
