import type { RssSubscriptionRead } from '@/types/api'

export interface RssFilterState {
  nameSearch: string
  enabledFilter: 'all' | 'enabled' | 'disabled'
  activeFilter: 'all' | 'active' | 'inactive'
  // 'stub' = no remote key yet (the "stub" badge); 'keyed' = has a key.
  keyFilter: 'all' | 'stub' | 'keyed'
  feedFilter: number | 'unlinked' | 'all'
}

export const DEFAULT_RSS_FILTERS: RssFilterState = {
  nameSearch: '',
  enabledFilter: 'all',
  activeFilter: 'all',
  keyFilter: 'all',
  feedFilter: 'all',
}

/** True when the subscription's name contains the (case-insensitive) search text. */
function matchesName(s: RssSubscriptionRead, search: string): boolean {
  return !search || s.name.toLowerCase().includes(search.toLowerCase())
}

function matchesEnabled(s: RssSubscriptionRead, filter: RssFilterState['enabledFilter']): boolean {
  if (filter === 'enabled') return s.enabled_in_config
  if (filter === 'disabled') return !s.enabled_in_config
  return true
}

function matchesActive(s: RssSubscriptionRead, filter: RssFilterState['activeFilter']): boolean {
  if (filter === 'active') return s.active
  if (filter === 'inactive') return !s.active
  return true
}

function matchesKey(s: RssSubscriptionRead, filter: RssFilterState['keyFilter']): boolean {
  if (filter === 'stub') return s.remote_key === null
  if (filter === 'keyed') return s.remote_key !== null
  return true
}

function matchesFeed(s: RssSubscriptionRead, filter: RssFilterState['feedFilter']): boolean {
  if (filter === 'unlinked') return s.feed_id === null
  if (typeof filter === 'number') return s.feed_id === filter
  return true
}

/**
 * Applies every Subscriptions-tab filter; a row must satisfy all of them.
 *
 * @param subs - All subscriptions.
 * @param f - The current filter state.
 * @returns The subscriptions that pass every filter, in their original order.
 */
export function filterSubscriptions(subs: RssSubscriptionRead[], f: RssFilterState): RssSubscriptionRead[] {
  return subs.filter(
    (s) =>
      matchesName(s, f.nameSearch) &&
      matchesEnabled(s, f.enabledFilter) &&
      matchesActive(s, f.activeFilter) &&
      matchesKey(s, f.keyFilter) &&
      matchesFeed(s, f.feedFilter),
  )
}
