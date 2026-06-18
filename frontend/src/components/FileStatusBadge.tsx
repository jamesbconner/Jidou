import clsx from 'clsx'
import type { FileStatus } from '@/types/api'

const STYLE: Record<FileStatus, string> = {
  pending: 'bg-gray-100 text-gray-600',
  downloading: 'bg-blue-100 text-blue-700',
  downloaded: 'bg-cyan-100 text-cyan-700',
  routing: 'bg-purple-100 text-purple-700',
  routed: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
}

export function FileStatusBadge({ status }: { status: FileStatus }) {
  return (
    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-medium capitalize', STYLE[status])}>
      {status}
    </span>
  )
}
