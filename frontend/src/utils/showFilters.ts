import type { ShowSortOrder } from '@/hooks/useShows'
import type { ShowList } from '@/types/api'

export interface ShowsFilterState {
  sort: ShowSortOrder
  filterContentType: string
  filterStatus: string
  filterGenre: string
  filterLanguage: string
  filterUpcoming: boolean
  filterMinRating: string
}

export const DEFAULT_SHOWS_FILTERS: ShowsFilterState = {
  sort: 'title_asc',
  filterContentType: '',
  filterStatus: '',
  filterGenre: '',
  filterLanguage: '',
  filterUpcoming: false,
  filterMinRating: '',
}

export interface MissingFilterState {
  filterContentType: string
  filterStatus: string
  filterGenre: string
  filterLanguage: string
  filterMinMissing: string
  filterFullSeasonMissing: string
  filterMaxOwned: string
  filterWatchlistOnly: boolean
}

export const DEFAULT_MISSING_FILTERS: MissingFilterState = {
  filterContentType: '',
  filterStatus: '',
  filterGenre: '',
  filterLanguage: '',
  filterMinMissing: '',
  filterFullSeasonMissing: '',
  filterMaxOwned: '',
  filterWatchlistOnly: false,
}

/**
 * Returns a sorted copy of `shows`; null/undefined sort keys always go last
 * for the nullable orders. Array.prototype.sort is stable, so ties keep the
 * incoming order.
 */
export function sortShows(shows: ShowList[], sort: ShowSortOrder): ShowList[] {
  function nullsLast<T>(
    a: T | null | undefined,
    b: T | null | undefined,
    cmp: (a: T, b: T) => number,
  ): number {
    if (a == null && b == null) return 0
    if (a == null) return 1
    if (b == null) return -1
    return cmp(a, b)
  }
  return shows.slice().sort((a, b) => {
    switch (sort) {
      case 'title_asc': return a.title.localeCompare(b.title)
      case 'title_desc': return b.title.localeCompare(a.title)
      case 'added_desc': return b.created_at.localeCompare(a.created_at)
      case 'added_asc': return a.created_at.localeCompare(b.created_at)
      case 'release_desc': return nullsLast(a.release_date, b.release_date, (x, y) => y.localeCompare(x))
      case 'release_asc': return nullsLast(a.release_date, b.release_date, (x, y) => x.localeCompare(y))
      case 'last_aired_desc': return nullsLast(a.last_air_date, b.last_air_date, (x, y) => y.localeCompare(x))
      case 'rating_desc': return nullsLast(a.vote_average, b.vote_average, (x, y) => y - x)
      case 'episodes_desc': return nullsLast(a.number_of_episodes, b.number_of_episodes, (x, y) => y - x)
      case 'episodes_added_desc':
        return nullsLast(a.latest_episode_added_at, b.latest_episode_added_at, (x, y) => y.localeCompare(x))
    }
  })
}

/** Library-tab filter: every non-empty criterion must match. */
export function applyFilters(
  shows: ShowList[],
  contentType: string,
  status: string,
  genre: string,
  language: string,
  upcoming: boolean,
  minRating: string,
): ShowList[] {
  return shows.filter((s) => {
    if (contentType === '__unset__') { if (s.content_type != null) return false }
    else if (contentType && s.content_type !== contentType) return false

    if (status && s.status !== status) return false

    if (genre && !s.genres?.some((g) => g.name === genre)) return false

    if (language && s.original_language !== language) return false

    if (upcoming && !s.next_episode_to_air) return false

    if (minRating) {
      const min = Number(minRating)
      if (s.vote_average == null || s.vote_average < min) return false
    }

    return true
  })
}

/** Missing-episodes-tab filter: every non-empty criterion must match. */
export function applyMissingFilters(
  shows: ShowList[],
  contentType: string,
  status: string,
  genre: string,
  language: string,
  minMissing: string,
  fullSeasonMissing: string,
  maxOwned: string,
  watchlistOnly: boolean,
  watchlistByShowId: Map<number, number>,
): ShowList[] {
  return shows.filter((s) => {
    if (contentType === '__unset__') { if (s.content_type != null) return false }
    else if (contentType && s.content_type !== contentType) return false

    if (status && s.status !== status) return false

    if (genre && !s.genres?.some((g) => g.name === genre)) return false

    if (language && s.original_language !== language) return false

    if (minMissing === 'eq1') { if (s.missing_episode_count !== 1) return false }
    else if (minMissing && s.missing_episode_count < Number(minMissing)) return false

    if (fullSeasonMissing && s.missing_full_season_count < Number(fullSeasonMissing)) return false

    if (maxOwned && s.matched_file_count > Number(maxOwned)) return false

    if (watchlistOnly && !watchlistByShowId.has(s.id)) return false

    return true
  })
}

export interface ShowFilterOptions {
  genres: string[]
  languages: string[]
  statuses: string[]
}

/** Distinct, sorted genre / language / status values present in `shows`. */
export function deriveFilterOptions(shows: ShowList[]): ShowFilterOptions {
  const genres = new Set<string>()
  const languages = new Set<string>()
  const statuses = new Set<string>()
  shows.forEach((s) => {
    s.genres?.forEach((g) => { if (g.name) genres.add(g.name as string) })
    if (s.original_language) languages.add(s.original_language)
    if (s.status) statuses.add(s.status)
  })
  return {
    genres: Array.from(genres).sort(),
    languages: Array.from(languages).sort(),
    statuses: Array.from(statuses).sort(),
  }
}
