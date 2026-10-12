import { SHOW_SORT_LABELS } from '@/hooks/useShows'
import type { ShowSortOrder } from '@/hooks/useShows'
import { Button } from '@/components/ui/Button'
import { SELECT_CLS } from './styles'

export type ShowsTab = 'library' | 'data' | 'missing'

interface ShowsHeaderProps {
  tab: ShowsTab
  /** Clear-filter count for the current tab; the button is hidden at 0 and on the data tab. */
  activeFilterCount: number
  onClearFilters: () => void
  sort: ShowSortOrder
  onSortChange: (sort: ShowSortOrder) => void
  onOpenSearch: () => void
}

/** Title row: clear-filters button, sort select (library tab) and the search trigger. */
export function ShowsHeader({
  tab,
  activeFilterCount,
  onClearFilters,
  sort,
  onSortChange,
  onOpenSearch,
}: ShowsHeaderProps) {
  const showClear = (tab === 'library' || tab === 'missing') && activeFilterCount > 0
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <h1 className="text-2xl font-bold mr-auto dark:text-gray-100">Shows</h1>
      {showClear && (
        <Button onClick={onClearFilters} variant="secondary" tone="light" size="sm">
          Clear filters ({activeFilterCount})
        </Button>
      )}
      {tab === 'library' && (
        <select value={sort} onChange={(e) => onSortChange(e.target.value as ShowSortOrder)} className={SELECT_CLS}>
          {(Object.entries(SHOW_SORT_LABELS) as [ShowSortOrder, string][]).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      )}
      <button
        onClick={onOpenSearch}
        className="border rounded-lg px-3 py-2 text-sm w-64 text-left text-gray-400 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:text-gray-500 dark:hover:bg-gray-800"
      >
        Search shows…
      </button>
    </div>
  )
}

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span className="ml-2 bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 text-xs rounded-full px-1.5 py-0.5">
      {count}
    </span>
  )
}

/** The Library / Data Quality / Missing Episodes tab bar with its count badges. */
export function ShowsTabBar({
  tab,
  onTabChange,
  libraryCount,
  dqIssues,
  missingEpisodes,
}: {
  tab: ShowsTab
  onTabChange: (tab: ShowsTab) => void
  libraryCount: number
  dqIssues: number
  missingEpisodes: number
}) {
  const tabCls = (t: ShowsTab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
    }`
  return (
    <div className="flex border-b">
      <button className={tabCls('library')} onClick={() => onTabChange('library')}>
        Shows in Library ({libraryCount})
      </button>
      <button className={tabCls('data')} onClick={() => onTabChange('data')}>
        Data Quality
        <CountBadge count={dqIssues} />
      </button>
      <button className={tabCls('missing')} onClick={() => onTabChange('missing')}>
        Missing Episodes
        <CountBadge count={missingEpisodes} />
      </button>
    </div>
  )
}
