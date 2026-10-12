import { useMemo } from 'react'
import { Link } from 'react-router'
import { DQ_CHECKS } from '@/utils/dqChecks'
import type { OrphanedTrackingRecord, ShowList } from '@/types/api'

interface DataQualityTabProps {
  allShows: ShowList[]
  isLoading: boolean
  orphans: OrphanedTrackingRecord[]
  /** Active issue filter key; owned by the page so it survives tab switches. */
  dqFilter: string | null
  onDqFilterChange: (key: string | null) => void
  onResolveOrphan: (orphan: OrphanedTrackingRecord) => void
  onDismissOrphan: (orphanId: number) => void
  /** Id of the orphan whose dismiss request is in flight, if any. */
  dismissingOrphanId: number | null
}

/**
 * Data-quality issue summary, issue table and unresolved orphan records.
 * Derives its counts and rows from page-owned props; the queries, the active
 * filter and the orphan mutations stay in `Shows`.
 */
export function DataQualityTab({
  allShows,
  isLoading,
  orphans,
  dqFilter,
  onDqFilterChange,
  onResolveOrphan,
  onDismissOrphan,
  dismissingOrphanId,
}: DataQualityTabProps) {
  const dqCounts = useMemo(
    () => Object.fromEntries(DQ_CHECKS.map((c) => [c.key, allShows.filter(c.test).length])),
    [allShows],
  )
  const dqRows = useMemo(() => {
    const check = dqFilter ? DQ_CHECKS.find((c) => c.key === dqFilter) : null
    return check
      ? allShows.filter(check.test)
      : allShows.filter((s) => DQ_CHECKS.some((c) => c.test(s)))
  }, [allShows, dqFilter])

  if (isLoading) {
    return <p className="text-gray-400 dark:text-gray-500 text-sm">Loading…</p>
  }

  return (
    <section className="space-y-6">
      {/* Metric summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {DQ_CHECKS.map((c) => {
          const count = dqCounts[c.key] ?? 0
          const active = dqFilter === c.key
          return (
            <button
              key={c.key}
              title={c.description}
              onClick={() => onDqFilterChange(active ? null : c.key)}
              className={`text-left rounded-lg border p-3 transition-colors ${
                active
                  ? 'border-amber-400 bg-amber-50 dark:bg-amber-950/40'
                  : count > 0
                    ? 'border-amber-200 bg-white hover:bg-amber-50 dark:bg-gray-900 dark:hover:bg-amber-950/30'
                    : 'border-gray-200 bg-white hover:bg-gray-50 dark:bg-gray-900 dark:hover:bg-gray-800'
              }`}
            >
              <p className={`text-2xl font-bold ${count > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-gray-400 dark:text-gray-500'}`}>
                {count}
              </p>
              <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5 leading-tight">{c.label}</p>
            </button>
          )
        })}
      </div>

      {/* Active filter description */}
      {dqFilter && (() => {
        const check = DQ_CHECKS.find((c) => c.key === dqFilter)!
        return (
          <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center gap-2">
            <span className="font-medium text-gray-700 dark:text-gray-300">{check.label}:</span>
            {check.description}
            <button onClick={() => onDqFilterChange(null)} className="ml-2 text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline">
              Show all issues
            </button>
          </p>
        )
      })()}

      {/* Issue table */}
      {dqRows.length === 0 && orphans.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">
          {dqFilter
            ? `No shows with this issue.`
            : `No data quality issues found across ${allShows.length} show${allShows.length !== 1 ? 's' : ''}.`}
        </p>
      ) : dqRows.length > 0 ? (
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b">
              <th className="pb-2 pr-4 font-medium">Title</th>
              <th className="pb-2 font-medium">Issues</th>
            </tr>
          </thead>
          <tbody>
            {dqRows.map((s) => {
              const issues = DQ_CHECKS.filter((c) => c.test(s))
              return (
                <tr key={s.id} className="border-b last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800">
                  <td className="py-2 pr-4 whitespace-nowrap">
                    <Link to={`/shows/${s.id}`} className="text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline font-medium">
                      {s.title}
                    </Link>
                  </td>
                  <td className="py-2">
                    <div className="flex gap-2 flex-wrap">
                      {issues.map((c) => (
                        <button
                          key={c.key}
                          title={c.description}
                          onClick={() => onDqFilterChange(c.key)}
                          className="bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded px-1.5 py-0.5 hover:bg-amber-200 dark:hover:bg-amber-900/70"
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}

      {/* Orphaned tracking records */}
      {orphans.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Unresolved tracking records</h3>
            <span className="bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 text-xs rounded-full px-1.5 py-0.5 font-medium">
              {orphans.length}
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">
            These episodes could not be migrated during a show rematch because their season/episode
            number has no match in the new TMDB entry. Select <strong>Match</strong> to link
            each file to the correct episode, or <strong>Dismiss</strong> to discard the record.
          </p>
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-xs text-gray-500 dark:text-gray-400 border-b">
                <th className="pb-2 pr-4 font-medium">Show</th>
                <th className="pb-2 pr-4 font-medium">File</th>
                <th className="pb-2 pr-4 font-medium">Old S/E</th>
                <th className="pb-2 pr-4 font-medium">Source</th>
                <th className="pb-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {orphans.map((o) => {
                const se = `S${String(o.old_season_number).padStart(2, '0')}E${String(o.old_episode_number).padStart(2, '0')}`
                const filename = o.tracked_filename_display
                  ? o.tracked_filename_display.replace(/\\/g, '/').split('/').pop() ??
                    o.tracked_filename_display
                  : '—'
                return (
                  <tr key={o.id} className="border-b last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800">
                    <td className="py-2 pr-4 whitespace-nowrap">
                      <Link to={`/shows/${o.show_id}`} className="text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline font-medium text-xs">
                        {o.show_title}
                      </Link>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-gray-600 dark:text-gray-400 max-w-xs truncate">
                      {filename}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-gray-500 dark:text-gray-400">{se}</td>
                    <td className="py-2 pr-4">
                      <span className={`text-xs font-medium ${o.tracked_source === 'import' ? 'text-blue-600' : 'text-green-600'}`}>
                        {o.tracked_source === 'import' ? 'import' : 'download'}
                      </span>
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => onResolveOrphan(o)}
                          className="text-xs bg-[var(--color-ocean-600)] text-white rounded px-2 py-0.5 hover:bg-[var(--color-ocean-500)] transition-colors"
                        >
                          Match
                        </button>
                        <button
                          onClick={() => onDismissOrphan(o.id)}
                          disabled={dismissingOrphanId === o.id}
                          className="text-xs bg-[var(--color-ember-600)] text-white rounded px-2 py-0.5 hover:bg-[var(--color-ember-500)] transition-colors disabled:opacity-50"
                        >
                          Dismiss
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
