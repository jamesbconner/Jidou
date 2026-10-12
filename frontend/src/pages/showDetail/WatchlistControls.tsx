import { useState } from 'react'
import { arrayMove } from '@dnd-kit/sortable'
import {
  useCreateWatchlistEntry,
  useDeleteWatchlistEntry,
  useReorderWatchlist,
} from '@/hooks/useWatchlist'
import { Badge } from '@/components/ui/Badge'
import type { WatchlistRead } from '@/types/api'

/** Add/remove-from-watchlist button; owns its own mutations. */
export function WatchlistToggleButton({
  showId,
  entryId,
}: {
  showId: number
  entryId: number | null
}) {
  const create = useCreateWatchlistEntry()
  const del = useDeleteWatchlistEntry()
  const pending = create.isPending || del.isPending
  const inWatchlist = entryId != null

  return (
    <button
      onClick={() => (inWatchlist ? del.mutate(entryId) : create.mutate({ show_id: showId }))}
      disabled={pending}
      className={`px-3 py-1.5 text-xs border rounded disabled:opacity-50 whitespace-nowrap ${
        inWatchlist
          ? 'border-[var(--color-ocean-300)] text-[var(--color-ocean-700)] bg-[var(--color-ocean-50)] hover:bg-[var(--color-ocean-100)] dark:bg-[var(--color-ocean-950)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/40'
          : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-800'
      }`}
    >
      {pending ? '…' : inWatchlist ? 'Remove From Watchlist' : 'Add To Watchlist'}
    </button>
  )
}

/** Queue badge that turns into a position select; owns its reorder mutation. */
export function QueuePositionSelect({
  entries,
  entryId,
}: {
  entries: WatchlistRead[]
  entryId: number
}) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const reorder = useReorderWatchlist()
  const index = entries.findIndex((e) => e.id === entryId)

  if (index === -1) return null

  if (!editing) {
    return (
      <>
        <Badge
          color="bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
          onClick={() => {
            setError(null)
            setEditing(true)
          }}
          title="Click to change queue position"
        >
          Queue #{index + 1}
        </Badge>
        {error && (
          <span className="text-xs text-red-600 dark:text-red-400" title={error}>
            Reorder failed
          </span>
        )}
      </>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={index}
      onChange={(e) => {
        const newIndex = Number(e.target.value)
        setEditing(false)
        if (newIndex === index) return
        reorder.mutate(arrayMove(entries, index, newIndex), {
          onError: (err) => {
            setError(err instanceof Error ? err.message : 'Failed to reorder')
          },
        })
      }}
      onBlur={() => setEditing(false)}
      className="text-xs border rounded px-1 py-0.5 bg-white text-gray-900 border-gray-300 dark:bg-gray-800 dark:text-gray-100 dark:border-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {entries.map((_, i) => (
        <option key={i} value={i} className="bg-white text-gray-900 dark:bg-gray-800 dark:text-gray-100">
          #{i + 1}
        </option>
      ))}
    </select>
  )
}
