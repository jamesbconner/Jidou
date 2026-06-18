import clsx from 'clsx'
import type { TaskStatus } from '@/types/api'

const STYLE: Record<TaskStatus, string> = {
  pending: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-orange-100 text-orange-700',
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-medium capitalize', STYLE[status])}>
      {status}
    </span>
  )
}
