import clsx from 'clsx'
import type { FileStatus } from '@/types/api'

const STYLE: Record<FileStatus, string> = {
  pending: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  discovered: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  downloading: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  downloaded: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300',
  unmatched: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-300',
  matched: 'bg-teal-100 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300',
  routing: 'bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300',
  routed: 'bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-300',
  error: 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300',
  seeded: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
  ignored: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
}

export function FileStatusBadge({ status }: { status: FileStatus }) {
  return (
    <span className={clsx('px-2 py-0.5 rounded-full text-xs font-medium capitalize', STYLE[status])}>
      {status}
    </span>
  )
}
