import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import {
  rssKeys,
  useRssRecommendations,
  usePatchRssSubscription,
  useBulkPatchRssSubscriptions,
} from '@/hooks/useRss'
import { badge } from '@/components/Badge'
import type { RssSubscriptionRecommendation } from '@/types/api'

export function RecommendationsTab() {
  const { data: recs = [], isLoading, refetch } = useRssRecommendations()
  const patch = usePatchRssSubscription()
  const bulkPatch = useBulkPatchRssSubscriptions()
  const [filter, setFilter] = useState<'all' | 'activate' | 'deactivate'>('all')
  const qc = useQueryClient()

  const visible = recs.filter((r) => filter === 'all' || r.recommendation === filter)
  const deactivateCount = recs.filter((r) => r.recommendation === 'deactivate').length
  const activateCount = recs.filter((r) => r.recommendation === 'activate').length

  const handleAcceptAll = () => {
    const items = visible.map((r) => ({ id: r.id, active: r.recommendation === 'activate' }))
    bulkPatch.mutate(items)
  }

  const handleAcceptOne = (rec: RssSubscriptionRecommendation) => {
    patch.mutate(
      { id: rec.id, update: { active: rec.recommendation === 'activate' } },
      { onSuccess: () => qc.invalidateQueries({ queryKey: rssKeys.recommendations() }) },
    )
  }

  if (isLoading) return <p className="text-sm text-gray-400 py-6">Loading recommendations…</p>

  return (
    <section className="space-y-4">
      {/* Summary + controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {(['all', 'deactivate', 'activate'] as const).map((f) => {
            const label =
              f === 'all'
                ? `All (${recs.length})`
                : f === 'deactivate'
                ? `Deactivate (${deactivateCount})`
                : `Activate (${activateCount})`
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 text-xs rounded-full border font-medium transition-colors ${
                  filter === f
                    ? f === 'deactivate'
                      ? 'bg-amber-100 border-amber-400 text-amber-800'
                      : f === 'activate'
                      ? 'bg-green-100 border-green-400 text-green-800'
                      : 'bg-indigo-100 border-indigo-400 text-indigo-800'
                    : 'border-gray-300 text-gray-500 hover:border-gray-400'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100"
          >
            Refresh
          </button>
          <button
            onClick={handleAcceptAll}
            disabled={visible.length === 0 || bulkPatch.isPending}
            className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {bulkPatch.isPending ? 'Applying…' : `Accept all (${visible.length})`}
          </button>
        </div>
      </div>

      {recs.length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-gray-400 text-sm">
          No recommendations — all subscriptions match their show&apos;s current status.
        </div>
      ) : visible.length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-gray-400 text-sm">
          No subscriptions match the current filter.
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-3 py-2">Subscription / Show</th>
                <th className="px-3 py-2 w-32">TMDB Status</th>
                <th className="px-3 py-2 w-24">Currently</th>
                <th className="px-3 py-2 w-32">Recommendation</th>
                <th className="px-3 py-2 w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visible.map((rec) => (
                <tr key={rec.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <p className="font-medium">{rec.name}</p>
                    {rec.show && (
                      <Link
                        to={`/shows/${rec.show.id}`}
                        className="text-xs text-indigo-500 hover:underline"
                      >
                        {rec.show.title} ↗
                      </Link>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600">
                    {rec.show?.status ?? '—'}
                  </td>
                  <td className="px-3 py-2">
                    {rec.active
                      ? badge('active', 'bg-green-100 text-green-700')
                      : badge('inactive', 'bg-gray-100 text-gray-500')}
                  </td>
                  <td className="px-3 py-2">
                    {rec.recommendation === 'deactivate'
                      ? badge('Deactivate', 'bg-amber-100 text-amber-700')
                      : badge('Activate', 'bg-green-100 text-green-700')}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => handleAcceptOne(rec)}
                      disabled={patch.isPending || bulkPatch.isPending}
                      className="text-xs text-indigo-600 hover:underline disabled:opacity-50"
                    >
                      Accept
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
