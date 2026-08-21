import { Fragment, useState } from 'react'
import { computeMissingEpisodes } from '@/utils/missingEpisodes'
import type { EpisodeList } from '@/types/api'

interface Props {
  episodes: EpisodeList[]
  /**
   * Server's local date (from GET /config), used as "today" so this
   * agrees with the server-computed missing_episode_count shown elsewhere
   * instead of drifting against the browser's own clock/timezone.
   */
  today?: string
}

/**
 * Library-completeness list view for a single show: aired episodes with no
 * linked file, grouped by season. Mirrors the row-per-item table used on the
 * Watchlist page, minus imagery — just the stats needed to act on gaps.
 */
export function MissingEpisodesList({ episodes, today }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const seasons = today ? computeMissingEpisodes(episodes, today) : computeMissingEpisodes(episodes)
  const totalMissing = seasons.reduce((sum, s) => sum + s.missing.length, 0)

  function toggle(seasonNumber: number) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(seasonNumber)) next.delete(seasonNumber)
      else next.add(seasonNumber)
      return next
    })
  }

  if (totalMissing === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500 italic">No missing episodes — up to date.</p>
  }

  return (
    <div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
        {totalMissing} missing episode{totalMissing === 1 ? '' : 's'} across {seasons.length}{' '}
        season{seasons.length === 1 ? '' : 's'}.
      </p>
      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-900 text-gray-500 dark:text-gray-400 text-xs uppercase">
            <tr>
              <th className="px-4 py-2 text-left">Season</th>
              <th className="px-4 py-2 text-left">Aired</th>
              <th className="px-4 py-2 text-left">Missing</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {seasons.map((s) => {
              const isOpen = expanded.has(s.seasonNumber)
              return (
                <Fragment key={s.seasonNumber}>
                  <tr
                    onClick={() => toggle(s.seasonNumber)}
                    className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-900"
                  >
                    <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100">
                      <span className="text-gray-400 dark:text-gray-500 mr-1">{isOpen ? '▾' : '▸'}</span>
                      Season {s.seasonNumber}
                    </td>
                    <td className="px-4 py-2 text-gray-500 dark:text-gray-400">{s.aired}</td>
                    <td className="px-4 py-2">
                      <span className="bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 text-xs font-medium rounded-full px-2 py-0.5">
                        {s.missing.length}
                      </span>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={3} className="px-4 py-2 bg-gray-50 dark:bg-gray-900">
                        <ul className="space-y-1">
                          {s.missing.map((ep) => (
                            <li key={ep.id} className="text-xs text-gray-600 dark:text-gray-300 flex gap-2">
                              <span className="text-gray-400 dark:text-gray-500 shrink-0">
                                S{String(s.seasonNumber).padStart(2, '0')}E
                                {String(ep.episode_number).padStart(2, '0')}
                              </span>
                              <span className="truncate">{ep.name}</span>
                              {ep.air_date && (
                                <span className="text-gray-400 dark:text-gray-500 shrink-0 ml-auto">
                                  {ep.air_date}
                                </span>
                              )}
                            </li>
                          ))}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
