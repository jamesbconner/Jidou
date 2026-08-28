import clsx from 'clsx'
import type { FileStatus } from '@/types/api'

const STYLE: Record<FileStatus, string> = {
  pending: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  discovered: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  downloading: 'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  downloaded: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300',
  unmatched: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950/40 dark:text-yellow-300',
  matched:
    'bg-[var(--color-haze-100)] text-[var(--color-haze-700)] dark:bg-[var(--color-haze-950)]/40 dark:text-[var(--color-haze-300)]',
  routing: 'bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300',
  routed:
    'bg-[var(--color-verdant-100)] text-[var(--color-verdant-700)] dark:bg-[var(--color-verdant-950)]/40 dark:text-[var(--color-verdant-300)]',
  error:
    'bg-[var(--color-ember-100)] text-[var(--color-ember-700)] dark:bg-[var(--color-ember-950)]/40 dark:text-[var(--color-ember-300)]',
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

