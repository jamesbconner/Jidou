import { useState } from 'react'
import { useWatchlist, useCreateWatchlistEntry, usePatchWatchlistEntry, useDeleteWatchlistEntry } from '@/hooks/useWatchlist'
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
  const patch = usePatchWatchlistEntry()

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
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
      onBlur={(e) => {
        setEditing(false)
        const next = e.target.value as WatchlistStatus
        if (next !== current) patch.mutate({ id, update: { status: next } })
      }}
      onChange={(e) => {
        const next = e.target.value as WatchlistStatus
        setEditing(false)
        if (next !== current) patch.mutate({ id, update: { status: next } })
      }}
      className="text-xs border rounded px-1 py-0.5 focus:outline-none focus:ring-1 focus:ring-blue-500"
    >
      {STATUS_OPTIONS.map((s) => (
        <option key={s} value={s}>{STATUS_LABEL[s]}</option>
      ))}
    </select>
  )
}

export default function Watchlist() {
  const [statusFilter, setStatusFilter] = useState<WatchlistStatus | ''>('')
  const { data: entries = [], isLoading } = useWatchlist(statusFilter || undefined)
  const createEntry = useCreateWatchlistEntry()
  const deleteEntry = useDeleteWatchlistEntry()

  const [newShowId, setNewShowId] = useState('')
  const [newStatus, setNewStatus] = useState<WatchlistStatus>('planned')

  function handleAdd() {
    const showId = parseInt(newShowId, 10)
    if (!showId) return
    createEntry.mutate(
      { show_id: showId, status: newStatus },
      { onSuccess: () => { setNewShowId(''); setNewStatus('planned') } },
    )
  }

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

      {/* Add entry form */}
      <div className="bg-white rounded-lg shadow p-4 flex items-end gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Show ID</label>
          <input
            type="number"
            min="1"
            placeholder="e.g. 42"
            value={newShowId}
            onChange={(e) => setNewShowId(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
            className="border rounded px-3 py-1.5 text-sm w-28 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Status</label>
          <select
            value={newStatus}
            onChange={(e) => setNewStatus(e.target.value as WatchlistStatus)}
            className="border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
        </div>
        <button
          onClick={handleAdd}
          disabled={!newShowId || createEntry.isPending}
          className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Add
        </button>
      </div>

      {/* Entries table */}
      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-gray-500 text-sm">No watchlist entries. Add a show above.</p>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left">#</th>
                <th className="px-4 py-2 text-left">Show ID</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Position</th>
                <th className="px-4 py-2 text-left">Added</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {entries.map((e, i) => (
                <tr key={e.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400 text-xs">{i + 1}</td>
                  <td className="px-4 py-2 font-medium">{e.show_id}</td>
                  <td className="px-4 py-2">
                    <InlineStatusSelect id={e.id} current={e.status} />
                  </td>
                  <td className="px-4 py-2 text-gray-500">{e.position}</td>
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
