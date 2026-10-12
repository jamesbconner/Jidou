import type { MediaPathEntry } from '@/types/api'

export function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 dark:text-gray-400 w-32 shrink-0">{label}</span>
      <span className="font-mono text-gray-800 dark:text-gray-200">{value}</span>
    </div>
  )
}

export function PathRow({ label, entry }: { label: string; entry: MediaPathEntry }) {
  return (
    <div className="flex gap-3 text-sm">
      <span className="text-gray-500 dark:text-gray-400 w-32 shrink-0">{label}</span>
      <div className="min-w-0">
        <div className="font-mono text-gray-800 dark:text-gray-200 truncate" title={entry.host}>
          {entry.host}
        </div>
        {entry.container !== entry.host && (
          <div
            className="font-mono text-xs text-gray-400 dark:text-gray-500 truncate"
            title={entry.container}
          >
            container: {entry.container}
          </div>
        )}
      </div>
    </div>
  )
}