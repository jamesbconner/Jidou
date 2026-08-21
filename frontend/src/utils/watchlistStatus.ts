import type { WatchlistStatus } from '@/types/api'

export const STATUS_OPTIONS: WatchlistStatus[] = [
  'planned',
  'watching',
  'completed',
  'on_hold',
  'dropped',
]

export const STATUS_LABEL: Record<WatchlistStatus, string> = {
  planned: 'Planned',
  watching: 'Watching',
  completed: 'Completed',
  on_hold: 'On Hold',
  dropped: 'Dropped',
}

export const STATUS_COLOR: Record<WatchlistStatus, string> = {
  planned: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  watching: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  completed: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  on_hold: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  dropped: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
}
