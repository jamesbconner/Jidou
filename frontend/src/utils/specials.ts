import type { ShowRead } from '@/types/api'

/** TMDB's Specials season. */
export const SPECIALS_SEASON = 0

/**
 * Whether a season name maps to the Specials season. Mirrors the backend's
 * `wants_specials`: such a name opts the show in to Specials syncing whatever
 * the Enable/Disable toggle says, so the toggle cannot turn it off.
 */
export function hasSpecialsSeasonName(show: Pick<ShowRead, 'season_aliases'>): boolean {
  return Object.values(show.season_aliases ?? {}).includes(SPECIALS_SEASON)
}
