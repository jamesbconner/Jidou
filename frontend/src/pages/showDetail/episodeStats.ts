import { computeMissingEpisodes } from '@/utils/missingEpisodes'
import type { EpisodeList } from '@/types/api'

export interface EpisodeStats {
  trackedCount: number
  watchedCount: number
  missingCount: number
  allWatched: boolean
}

/**
 * Derives the counts the ShowDetail header and tabs display.
 *
 * Pure so the page component stays free of the counting branches.
 *
 * @param episodes - Every episode of the show.
 * @param trackMissing - Whether the show tracks missing episodes at all.
 * @param today - Server "today" (ISO date); falls back to the browser's date when empty.
 * @returns Tracked/watched/missing counts and whether every episode is watched.
 */
export function episodeStats(
  episodes: EpisodeList[],
  trackMissing: boolean,
  today: string | undefined,
): EpisodeStats {
  const trackedCount = episodes.filter((e) => e.file_tracked).length
  const watchedCount = episodes.filter((e) => e.watched).length
  const missingCount = trackMissing
    ? computeMissingEpisodes(episodes, today || undefined).reduce((sum, s) => sum + s.missing.length, 0)
    : 0
  const allWatched = episodes.length > 0 && watchedCount === episodes.length
  return { trackedCount, watchedCount, missingCount, allWatched }
}
