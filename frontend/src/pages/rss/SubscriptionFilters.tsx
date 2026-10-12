import type { RssFeedRead } from '@/types/api'
import type { RssFilterState } from '@/pages/rss/rssFilters'

const SELECT_CLS =
  'border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)] dark:bg-gray-800 dark:text-gray-100'

/** Parses the feed <select> value back into the filter's number | 'all' | 'unlinked'. */
function parseFeedFilter(v: string): RssFilterState['feedFilter'] {
  if (v === 'all' || v === 'unlinked') return v
  return Number(v)
}

interface SubscriptionFiltersProps {
  filters: RssFilterState
  onChange: (patch: Partial<RssFilterState>) => void
  feeds: RssFeedRead[]
  shown: number
  total: number
}

/** Filter bar above the subscriptions table. */
export function SubscriptionFilters({ filters, onChange, feeds, shown, total }: SubscriptionFiltersProps) {
  const { nameSearch, enabledFilter, activeFilter, keyFilter, feedFilter } = filters
  return (
    <div className="flex flex-wrap gap-2 items-center mb-3">
      <input
        type="search"
        value={nameSearch}
        onChange={(e) => onChange({ nameSearch: e.target.value })}
        placeholder="Search name…"
        className="border rounded px-2 py-1 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)] dark:bg-gray-800 dark:text-gray-100"
      />
      <select
        value={enabledFilter}
        onChange={(e) => onChange({ enabledFilter: e.target.value as typeof enabledFilter })}
        className={SELECT_CLS}
      >
        <option value="all">Any enabled</option>
        <option value="enabled">Enabled</option>
        <option value="disabled">Disabled</option>
      </select>
      <select
        value={activeFilter}
        onChange={(e) => onChange({ activeFilter: e.target.value as typeof activeFilter })}
        className={SELECT_CLS}
      >
        <option value="all">Any active</option>
        <option value="active">Active</option>
        <option value="inactive">Inactive</option>
      </select>
      <select
        aria-label="Key filter"
        value={keyFilter}
        onChange={(e) => onChange({ keyFilter: e.target.value as typeof keyFilter })}
        className={SELECT_CLS}
      >
        <option value="all">Any key</option>
        <option value="stub">Stub (no key)</option>
        <option value="keyed">Has key</option>
      </select>
      <select
        value={String(feedFilter)}
        onChange={(e) => onChange({ feedFilter: parseFeedFilter(e.target.value) })}
        className={SELECT_CLS}
      >
        <option value="all">All feeds</option>
        <option value="unlinked">Unlinked</option>
        {feeds.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
      </select>
      <span className="text-xs text-gray-400 dark:text-gray-500 ml-1">{shown} / {total}</span>
    </div>
  )
}
