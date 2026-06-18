import type { TaskList } from '@/types/api'
import { TaskStatusBadge } from './TaskStatusBadge'
import clsx from 'clsx'

interface Props {
  task: TaskList
  onCancel?: () => void
}

export function TaskProgressBar({ task, onCancel }: Props) {
  const pct =
    task.progress_total > 0
      ? Math.round((task.progress_current / task.progress_total) * 100)
      : 0

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{task.task_type}</span>
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
    </div>
  )
}
