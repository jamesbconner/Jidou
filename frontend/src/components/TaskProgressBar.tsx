import type { TaskList } from '@/types/api'
import { TaskStatusBadge } from './TaskStatusBadge'
import clsx from 'clsx'

interface Props {
  task: TaskList
  onCancel?: () => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`
  return `${(bytes / 1073741824).toFixed(2)} GB`
}

type Stat = { label: string; value: string | number; highlight?: boolean }

function buildStats(task: TaskList): Stat[] {
  const s = task.result_summary
  if (!s) return []

  const n = (key: string) => (s[key] as number) ?? 0

  switch (task.task_type) {
    case 'scan':
      return [
        { label: 'paths scanned', value: n('paths_scanned') },
        { label: 'new files', value: n('files_created'), highlight: n('files_created') > 0 },
        { label: 'skipped', value: n('files_skipped') },
      ]
    case 'download':
      return [
        { label: 'downloaded', value: n('files_downloaded'), highlight: n('files_downloaded') > 0 },
        { label: '', value: formatBytes(n('bytes_downloaded')) },
        ...(n('files_failed') > 0 ? [{ label: 'failed', value: n('files_failed'), highlight: true }] : []),
      ]
    case 'match':
      return [
        { label: 'matched', value: n('files_matched'), highlight: n('files_matched') > 0 },
        { label: 'unmatched', value: n('files_unmatched') },
        { label: 'processed', value: n('files_processed') },
        ...(n('files_failed') > 0 ? [{ label: 'failed', value: n('files_failed'), highlight: true }] : []),
      ]
    case 'route':
      return [
        { label: 'routed', value: n('files_routed'), highlight: n('files_routed') > 0 },
        ...(n('files_failed') > 0 ? [{ label: 'failed', value: n('files_failed'), highlight: true }] : []),
      ]
    case 'sync':
      return [
        { label: 'discovered', value: n('files_created') },
        { label: 'downloaded', value: n('files_downloaded') },
        { label: 'matched', value: n('files_matched'), highlight: n('files_matched') > 0 },
        { label: 'routed', value: n('files_routed'), highlight: n('files_routed') > 0 },
        ...(n('episodes_upserted') > 0 ? [{ label: 'episodes synced', value: n('episodes_upserted') }] : []),
      ]
    default:
      return []
  }
}

export function TaskProgressBar({ task, onCancel }: Props) {
  const pct =
    task.progress_total > 0
      ? Math.round((task.progress_current / task.progress_total) * 100)
      : 0

  const stats = buildStats(task)

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="font-medium capitalize">{task.task_type}</span>
          {task.dry_run && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">
              dry run
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <TaskStatusBadge status={task.status} />
          {(task.status === 'pending' || task.status === 'running') && onCancel && (
            <button
              onClick={onCancel}
              className="text-xs text-red-600 hover:underline"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      {task.progress_total > 0 && (
        <div className="w-full bg-gray-200 rounded-full h-1.5">
          <div
            className={clsx(
              'h-1.5 rounded-full transition-all duration-300',
              task.status === 'completed' ? 'bg-green-500' :
              task.status === 'failed' ? 'bg-red-500' :
              'bg-blue-500',
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}

      {task.progress_message && (
        <p className="text-xs text-gray-500 truncate">{task.progress_message}</p>
      )}

      {stats.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-0.5 pt-0.5">
          {stats.map((st, i) => (
            <span key={i} className="text-xs text-gray-500">
              <span className={clsx('font-semibold', st.highlight ? 'text-gray-800' : 'text-gray-600')}>
                {st.value}
              </span>
              {st.label && ` ${st.label}`}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
