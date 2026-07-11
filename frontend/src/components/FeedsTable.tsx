import { useState } from 'react'
import { usePatchRssFeed, useDeleteRssFeed } from '@/hooks/useRss'
import { badge } from '@/components/Badge'
import { FeedFormModal } from '@/components/FeedFormModal'
import type { RssFeedRead } from '@/types/api'

export function FeedsTable({ feeds }: { feeds: RssFeedRead[] }) {
  const patch = usePatchRssFeed()
  const del = useDeleteRssFeed()
  const [editFeed, setEditFeed] = useState<RssFeedRead | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <>
      {createOpen && <FeedFormModal feed={null} onClose={() => setCreateOpen(false)} />}
      {editFeed && <FeedFormModal feed={editFeed} onClose={() => setEditFeed(null)} />}

      <div className="flex justify-end mb-2">
        <button
          onClick={() => setCreateOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          + New Feed
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 w-12">Key</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2 max-w-[200px]">URL</th>
              <th className="px-3 py-2">Default Download</th>
              <th className="px-3 py-2">Default Move</th>
              <th className="px-3 py-2 w-24" title="Inactive feeds are excluded from the published YaRSS2 config.">Active</th>
              <th className="px-3 py-2 w-24"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {feeds.map((f) => (
              <tr key={f.id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{f.remote_key ?? '—'}</td>
                <td className="px-3 py-2 font-medium">
                  <button onClick={() => setEditFeed(f)} className="hover:text-indigo-600 hover:underline text-left">
                    {f.name}
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 max-w-[200px] truncate">
                  <a href={f.url} target="_blank" rel="noreferrer" className="hover:underline" title={f.url}>{f.url}</a>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{f.default_download_location ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{f.default_move_completed ?? '—'}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => patch.mutate({ id: f.id, update: { active: !f.active } })}
                    title={f.active
                      ? 'Active — included in published config. Click to deactivate.'
                      : 'Inactive — excluded from published config. Click to activate.'}
                    aria-label={f.active ? 'Feed active — click to deactivate' : 'Feed inactive — click to activate'}
                    aria-pressed={f.active}
                  >
                    {f.active
                      ? badge('active', 'bg-green-100 text-green-700 hover:ring-1 hover:ring-green-400')
                      : badge('inactive', 'bg-gray-100 text-gray-500 hover:ring-1 hover:ring-gray-400')}
                  </button>
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <button onClick={() => setEditFeed(f)} className="text-xs text-gray-500 hover:underline">Edit</button>
                    <button
                      onClick={() => { if (confirm(`Delete feed "${f.name}"?`)) del.mutate(f.id) }}
                      className="text-xs text-red-400 hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {feeds.length === 0 && (
          <p className="text-center text-gray-400 py-8 text-sm">No feeds. Run an import or create one manually.</p>
        )}
      </div>
    </>
  )
}
