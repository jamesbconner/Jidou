import { Link } from 'react-router'
import type { TaskRead } from '@/types/api'

function TaskStatusBadge({ task }: { task: TaskRead | undefined }) {
  if (!task) return null
  const colors: Record<string, string> = {
    completed: 'text-green-600',
    failed: 'text-red-500',
    running: 'text-blue-500',
    pending: 'text-yellow-600',
  }
  return (
    <span className={`text-xs font-medium ${colors[task.status] ?? 'text-gray-500'}`}>
      {task.status}{task.progress_message ? ` — ${task.progress_message}` : ''}
    </span>
  )
}

/** The slice of a react-query mutation the header reads. */
interface ActionState {
  isPending: boolean
  isError: boolean
  error: unknown
}

/** One-line inline error for a failed header action. */
function ActionError({ prefix, action }: { prefix: string; action: ActionState }) {
  if (!action.isError) return null
  return (
    <p className="text-xs text-red-600 dark:text-red-400">
      {prefix}: {(action.error as Error)?.message ?? 'Unknown error'}
    </p>
  )
}

const SOLID_BTN = 'px-4 py-2 text-sm rounded bg-gray-200 text-gray-700 hover:bg-gray-300 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'

interface RssHeaderProps {
  triggerImport: ActionState
  triggerPublish: ActionState
  download: ActionState
  diff: ActionState
  importTask: TaskRead | undefined
  publishTask: TaskRead | undefined
  onImport: () => void
  onPublish: () => void
  onDownload: () => void
  onDiff: () => void
}

/** Page title plus the import / publish / download / diff actions and their status lines. */
export function RssHeader({
  triggerImport,
  triggerPublish,
  download,
  diff,
  importTask,
  publishTask,
  onImport,
  onPublish,
  onDownload,
  onDiff,
}: RssHeaderProps) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">RSS</h1>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Manage YaRSS2 feeds and subscriptions. Import from or publish to the remote config file.
        </p>
      </div>
      <div className="flex flex-col gap-2 items-end">
        <div className="flex gap-2 items-center">
          <button
            onClick={onImport}
            disabled={triggerImport.isPending}
            className="px-4 py-2 text-sm rounded bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50"
          >
            {triggerImport.isPending ? 'Dispatching…' : 'Import from server'}
          </button>
          <button
            onClick={onPublish}
            disabled={triggerPublish.isPending}
            className="px-4 py-2 text-sm rounded bg-[var(--color-ocean-600)] text-white hover:bg-[var(--color-ocean-700)] disabled:opacity-50"
          >
            {triggerPublish.isPending ? 'Dispatching…' : 'Publish to server'}
          </button>
          <div className="w-px h-6 bg-gray-300 dark:bg-gray-700 mx-1" />
          <button onClick={onDownload} disabled={download.isPending} className={SOLID_BTN}>
            {download.isPending ? 'Downloading…' : 'Download'}
          </button>
          <button onClick={onDiff} disabled={diff.isPending} className={SOLID_BTN}>
            {diff.isPending ? 'Comparing…' : 'Diff'}
          </button>
        </div>
        {importTask && <div className="text-right text-xs dark:text-gray-300">Import: <TaskStatusBadge task={importTask} /></div>}
        {publishTask && <div className="text-right text-xs dark:text-gray-300">Publish: <TaskStatusBadge task={publishTask} /></div>}
        <ActionError prefix="Import failed to start" action={triggerImport} />
        <ActionError prefix="Publish failed to start" action={triggerPublish} />
        <ActionError prefix="Download failed" action={download} />
        <ActionError prefix="Diff failed" action={diff} />
        <p className="text-xs text-gray-400 dark:text-gray-500">
          Check the <Link to="/tasks" className="text-[var(--color-ocean-500)] dark:text-[var(--color-ocean-400)] hover:underline">Tasks page</Link> for details.
        </p>
      </div>
    </div>
  )
}
