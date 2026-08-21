import clsx from 'clsx'
import type { TaskStatus } from '@/types/api'

const STYLE: Record<TaskStatus, string> = {
  pending: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  running: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300',
  failed: 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300',
  cancelled: 'bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300',
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-medium capitalize', STYLE[status])}>
      {status}
    </span>
  )
}
