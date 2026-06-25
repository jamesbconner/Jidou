import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useWatchlist, usePatchWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
import type { WatchlistStatus } from '@/types/api'

const STATUS_OPTIONS: WatchlistStatus[] = ['planned', 'watching', 'completed', 'on_hold', 'dropped']

const STATUS_LABEL: Record<WatchlistStatus, string> = {
  planned: 'Planned',
  watching: 'Watching',
  completed: 'Completed',
  on_hold: 'On Hold',
  dropped: 'Dropped',
}

const STATUS_COLOR: Record<WatchlistStatus, string> = {
  planned: 'bg-gray-100 text-gray-700',
  watching: 'bg-blue-100 text-blue-700',
  completed: 'bg-green-100 text-green-700',
  on_hold: 'bg-yellow-100 text-yellow-700',
  dropped: 'bg-red-100 text-red-700',
}

function InlineStatusSelect({ id, current }: { id: number; current: WatchlistStatus }) {
  const [editing, setEditing] = useState(false)
  const pendingRef = useRef<WatchlistStatus>(current)
  const patch = usePatchWatchlistEntry()

  if (!editing) {
    return (
      <button
        onClick={() => { pendingRef.current = current; setEditing(true) }}
        className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_COLOR[current]} hover:opacity-80`}
        title="Click to change status"
      >
        {STATUS_LABEL[current]}
      </button>
    )
  }

  return (
    <select
      autoFocus
      defaultValue={current}
      onChange={(e) => { pendingRef.current = e.target.value as WatchlistStatus }}
      onBlur={() => {
        setEditing(false)
        if (pendingRef.current !== current) patch.mutate({ id, update: { status: pendingRef.current } })
      }}
      className="text-xs border rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>{STATUS_LABEL[s]}</option>
      ))}
    </select>
  )
}

function InlineNotes({ id, notes }: { id: number; notes: string | null }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(notes ?? '')
  const cancelRef = useRef(false)
  const patch = usePatchWatchlistEntry()

  function commit() {
    if (cancelRef.current) { cancelRef.current = false; return }
    setEditing(false)
    const trimmed = value.trim()
    const next = trimmed === '' ? null : trimmed
    if (next !== notes) patch.mutate({ id, update: { notes: next } })
  }

  if (!editing) {
    return (
      <button
        onClick={() => { cancelRef.current = false; setValue(notes ?? ''); setEditing(true) }}
        className="text-left text-gray-500 hover:text-blue-600 hover:underline max-w-[12rem] truncate block"
        title={notes ?? 'Click to add notes'}
      >
        {notes ?? '—'}
      </button>
    )
  }

  return (
    <input
      type="text"
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') { cancelRef.current = true; setValue(notes ?? ''); setEditing(false) }
      }}
      className="border rounded px-1 py-0.5 text-xs w-36 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  )
}

export default function Watchlist() {
  const [statusFilter, setStatusFilter] = useState<WatchlistStatus | ''>('')
  const { data: entries = [], isLoading } = useWatchlist(statusFilter || undefined)
  const deleteEntry = useDeleteWatchlistEntry()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Watchlist</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as WatchlistStatus | '')}
          className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>
      </div>

      <p className="text-sm text-gray-500">
        Add shows to your watchlist using the eye icon on any show card in the{' '}
        <Link to="/shows" className="text-blue-600 hover:underline">Library</Link>.
      </p>

      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-gray-500 text-sm">No watchlist entries yet.</p>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left w-8">#</th>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Notes</th>
                <th className="px-4 py-2 text-left">Added</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {entries.map((e, i) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400 text-xs">{i + 1}</td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/shows/${e.show_id}`}
                      className="font-medium hover:underline text-blue-700"
                    >
                      {e.show.title}
                    </Link>
                    <span className="block text-xs text-gray-400">TMDB #{e.show.tmdb_id}</span>
                  </td>
                  <td className="px-4 py-2">
                    <InlineStatusSelect id={e.id} current={e.status} />
                  </td>
                  <td className="px-4 py-2">
                    <InlineNotes id={e.id} notes={e.notes} />
                  </td>
                  <td className="px-4 py-2 text-gray-400 text-xs">
                    {new Date(e.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => deleteEntry.mutate(e.id)}
                      disabled={deleteEntry.isPending}
                      className="text-xs text-red-500 hover:underline disabled:opacity-50"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
