import { useState } from 'react'
import { Link } from 'react-router-dom'
import { usePatchRssSubscription, useDeleteRssSubscription } from '@/hooks/useRss'
import { badge } from '@/components/Badge'
import { SubscriptionCreateModal } from '@/components/SubscriptionCreateModal'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import { SubPreviewModal } from '@/components/SubPreviewModal'
import type { RssFeedRead, RssSubscriptionRead } from '@/types/api'

export function SubscriptionsTable({ subs, feeds }: { subs: RssSubscriptionRead[]; feeds: RssFeedRead[] }) {
  const patch = usePatchRssSubscription()
  const del = useDeleteRssSubscription()
  const [editSub, setEditSub] = useState<RssSubscriptionRead | null>(null)
  const [previewSub, setPreviewSub] = useState<RssSubscriptionRead | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <>
      {createOpen && <SubscriptionCreateModal feeds={feeds} onClose={() => setCreateOpen(false)} />}
      {editSub && <SubscriptionEditModal sub={editSub} feeds={feeds} onClose={() => setEditSub(null)} />}
      {previewSub && <SubPreviewModal sub={previewSub} onClose={() => setPreviewSub(null)} />}

      <div className="flex justify-end mb-2">
        <button
          onClick={() => setCreateOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          + New Subscription
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 w-16">Key</th>
              <th className="px-3 py-2">Name / Show</th>
              <th className="px-3 py-2 w-20" title="Included in the published YaRSS2 config. Stubs are excluded until explicitly enabled.">Enabled</th>
              <th className="px-3 py-2 w-24" title="Jidou controls this flag. Active subscriptions are treated as live by the downloader. Stubs are always inactive.">Active</th>
              <th className="px-3 py-2 w-36"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subs.map((sub) => {
              const isStub = sub.remote_key === null && !sub.enabled_in_config
              return (
                <tr key={sub.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">
                    {sub.remote_key ?? badge('stub', 'bg-yellow-100 text-yellow-700')}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setEditSub(sub)}
                      className="font-medium text-left hover:text-indigo-600 hover:underline"
                      title="Edit subscription"
                    >
                      {sub.name}
                    </button>
                    {sub.show && (
                      <Link to={`/shows/${sub.show.id}`} className="block text-xs text-indigo-500 hover:underline">
                        {sub.show.title}
                      </Link>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => patch.mutate({ id: sub.id, update: { enabled_in_config: !sub.enabled_in_config } })}
                      className={`w-10 h-5 rounded-full transition-colors ${sub.enabled_in_config ? 'bg-green-500' : 'bg-gray-300'}`}
                      title={sub.enabled_in_config
                        ? 'Enabled — included in published config. Click to disable.'
                        : 'Disabled — not included in published config. Click to enable.'}
                      aria-label={sub.enabled_in_config ? 'Enabled in config — click to disable' : 'Disabled from config — click to enable'}
                      aria-pressed={sub.enabled_in_config}
                    >
                      <span className={`block w-4 h-4 bg-white rounded-full shadow transform transition-transform mx-0.5 ${sub.enabled_in_config ? 'translate-x-5' : 'translate-x-0'}`} />
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    {isStub ? (
                      <span
                        title="Stubs are always inactive until promoted to a real subscription."
                        className="cursor-default"
                      >
                        {badge('inactive', 'bg-gray-100 text-gray-400')}
                      </span>
                    ) : (
                      <button
                        onClick={() => patch.mutate({ id: sub.id, update: { active: !sub.active } })}
                        title={sub.active
                          ? 'Active — downloader treats this as live. Click to deactivate.'
                          : 'Inactive — downloader skips this. Click to activate.'}
                        aria-label={sub.active ? 'Active — click to deactivate' : 'Inactive — click to activate'}
                        aria-pressed={sub.active}
                      >
                        {sub.active
                          ? badge('active', 'bg-green-100 text-green-700 hover:ring-1 hover:ring-green-400')
                          : badge('inactive', 'bg-gray-100 text-gray-500 hover:ring-1 hover:ring-gray-400')}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2 items-center">
                      <button onClick={() => setEditSub(sub)} className="text-xs text-gray-500 hover:underline">Edit</button>
                      <button onClick={() => setPreviewSub(sub)} className="text-xs text-gray-500 hover:underline">Preview</button>
                      {!sub.enabled_in_config && (
                        <button
                          onClick={() => { if (confirm(`Delete subscription "${sub.name}"?`)) del.mutate(sub.id) }}
                          className="text-xs text-red-400 hover:underline"
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {subs.length === 0 && (
          <p className="text-center text-gray-400 py-8 text-sm">No subscriptions match the filter.</p>
        )}
      </div>
    </>
  )
}
