import { useShow, useShowEpisodes } from '@/hooks/useShows'
import { useFilesByShow } from '@/hooks/useFiles'
import { useRssSubscriptions, useRssFeeds } from '@/hooks/useRss'
import { useWatchlist } from '@/hooks/useWatchlist'
import { useConfig } from '@/hooks/useConfig'

/**
 * Loads every read-side query the ShowDetail page needs.
 *
 * Kept in one hook so the page component is left with UI state and mutations
 * only. It must stay called from the page itself (not a child), so the queries
 * keep their original lifetime and fire in the same order on mount.
 *
 * @param showId - Id of the show on the current route.
 */
export function useShowDetailData(showId: number) {
  const { data: show, isLoading } = useShow(showId)
  const { data: config } = useConfig()
  const { data: episodes = [] } = useShowEpisodes(showId)
  const isMovie = (show?.content_type ?? show?.media_type) === 'movie'
  const { data: movieFiles = [] } = useFilesByShow(showId, isMovie)
  const { data: rssSubs = [] } = useRssSubscriptions({ show_id: showId })
  const { data: rssFeeds = [] } = useRssFeeds()
  // TODO: fetches the entire watchlist just to look up this one show (no by-show
  // API filter exists yet). Add a `show_id` filter to GET /watchlist and use it
  // here; keep a lazy full-list fetch (enabled only once this show is confirmed
  // on the watchlist) for the Queue #N position/reorder dropdown.
  const { data: watchlistEntries = [] } = useWatchlist(undefined, 10000)

  return {
    show,
    episodes,
    movieFiles,
    config,
    rssSubs,
    rssFeeds,
    watchlistEntries,
    isMovie,
    isLoading,
  }
}
