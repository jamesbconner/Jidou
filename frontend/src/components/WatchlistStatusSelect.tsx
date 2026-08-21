import { useState } from 'react'
import { usePatchWatchlistEntry } from '@/hooks/useWatchlist'
import { Badge } from '@/components/ui/Badge'
import { STATUS_COLOR, STATUS_LABEL, STATUS_OPTIONS } from '@/utils/watchlistStatus'
import type { WatchlistStatus } from '@/types/api'

interface Props {
  id: number
  current: WatchlistStatus
}

export function WatchlistStatusSelect({ id, current }: Props) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const patch = usePatchWatchlistEntry()

  if (!editing) {
    return (
      <>
        <Badge
          color={STATUS_COLOR[current]}
          onClick={() => {
            setError(null)
            setEditing(true)
          }}
          title="Click to change status"
        >
          {STATUS_LABEL[current]}
        </Badge>
        {error && (
          <span className="text-xs text-red-600 dark:text-red-400" title={error}>
            Update failed
          </span>
        )}
      </>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={current}
      onChange={(e) => {
        const next = e.target.value as WatchlistStatus
        if (next !== current) {
          patch.mutate(
            { id, update: { status: next } },
            {
              onError: (err) => {
                setError(err instanceof Error ? err.message : 'Failed to update status')
              },
            },
          )
        }
      }}
      onBlur={() => setEditing(false)}
      className="text-xs border rounded px-1 py-0.5 dark:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>
          {STATUS_LABEL[s]}
        </option>
      ))}
    </select>
  )
}
