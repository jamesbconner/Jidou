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
  planned: 'bg-gray-100 text-gray-700',
  watching: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  on_hold: 'bg-yellow-100 text-yellow-700',
  dropped: 'bg-red-100 text-red-700',
}
