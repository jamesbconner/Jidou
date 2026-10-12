import { useShow, useShowEpisodes } from '@/hooks/useShows'
import { useFilesByShow } from '@/hooks/useFiles'
import { useRssSubscriptions, useRssFeeds } from '@/hooks/useRss'
import { useWatchlist, useWatchlistEntryForShow } from '@/hooks/useWatchlist'
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
  // Membership comes from the by-show filter, so a show that is not on the
  // watchlist never fetches the whole list. The full list is loaded only once
  // the show is confirmed on the watchlist: the Queue #N position/reorder
  // select needs every entry in queue order.
  const { data: watchlistEntry = null } = useWatchlistEntryForShow(showId)
  const { data: watchlistEntries = [] } = useWatchlist(undefined, 10000, {
    enabled: watchlistEntry !== null,
  })

  return {
    show,
    episodes,
    movieFiles,
    config,
    rssSubs,
    rssFeeds,
    watchlistEntry,
    watchlistEntries,
    isMovie,
    isLoading,
  }
}
