import { useRef, useState } from 'react'
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
  const pendingRef = useRef<WatchlistStatus>(current)
  const patch = usePatchWatchlistEntry()

  if (!editing) {
    return (
      <Badge
        color={STATUS_COLOR[current]}
        onClick={() => {
          pendingRef.current = current
          setEditing(true)
        }}
        title="Click to change status"
      >
        {STATUS_LABEL[current]}
      </Badge>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={current}
      onChange={(e) => {
        const next = e.target.value as WatchlistStatus
        pendingRef.current = next
        if (next !== current) patch.mutate({ id, update: { status: next } })
      }}
      onBlur={() => setEditing(false)}
      className="text-xs border rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>
          {STATUS_LABEL[s]}
        </option>
      ))}
    </select>
  )
}
