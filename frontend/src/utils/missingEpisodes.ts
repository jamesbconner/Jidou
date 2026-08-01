import type { EpisodeList } from '@/types/api'

export interface SeasonGap {
  seasonNumber: number
  aired: number
  missing: EpisodeList[]
}

/**
 * Group aired-but-untracked episodes by season.
 *
 * An episode counts as a gap when it has already aired (`air_date` is in the
 * past relative to `today`) and has no linked file (`file_tracked` is
 * false). Episodes with no `air_date` (unannounced/TBD) are never gaps.
 *
 * @param episodes - Episodes for a single show.
 * @param today - ISO date string (YYYY-MM-DD) used as "now"; defaults to the
 *   current date. Exposed as a parameter so tests don't depend on the clock.
 * @returns Seasons with at least one gap, ordered by season number, each with
 *   its missing episodes ordered by episode number.
 */
export function computeMissingEpisodes(
  episodes: EpisodeList[],
  today: string = new Date().toISOString().slice(0, 10),
): SeasonGap[] {
  const bySeason = new Map<number, { aired: number; missing: EpisodeList[] }>()

  for (const ep of episodes) {
    if (!ep.air_date) continue
    const entry = bySeason.get(ep.season_number) ?? { aired: 0, missing: [] }
    if (ep.air_date < today) {
      entry.aired += 1
      if (!ep.file_tracked) entry.missing.push(ep)
    }
    bySeason.set(ep.season_number, entry)
  }

  return [...bySeason.entries()]
    .filter(([, entry]) => entry.missing.length > 0)
    .sort(([a], [b]) => a - b)
    .map(([seasonNumber, entry]) => ({
      seasonNumber,
      aired: entry.aired,
      missing: [...entry.missing].sort((a, b) => a.episode_number - b.episode_number),
    }))
}
