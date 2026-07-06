import { RECENT_SORT_LABELS, type RecentSort } from '@/hooks/useDashboard'

const CARD_COUNT_OPTIONS = [6, 12, 18, 24, 36]
const CONTENT_TYPE_OPTIONS = ['anime', 'tv', 'movie']

interface Props {
  sort: RecentSort
  onSortChange: (sort: RecentSort) => void
  genre: string
  onGenreChange: (genre: string) => void
  genreOptions: string[]
  contentType: string
  onContentTypeChange: (contentType: string) => void
  limit: number
  onLimitChange: (limit: number) => void
}

const selectCls =
  'border rounded px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-indigo-400'

/** Shared sort/genre/content-type/card-count control row for a dashboard carousel section. */
export function DashboardSectionControls({
  sort,
  onSortChange,
  genre,
  onGenreChange,
  genreOptions,
  contentType,
  onContentTypeChange,
  limit,
  onLimitChange,
}: Props) {
  return (
    <div className="flex gap-2 flex-wrap items-center">
      <select
        value={sort}
        onChange={(e) => onSortChange(e.target.value as RecentSort)}
        className={selectCls}
        aria-label="Sort order"
      >
        {(Object.entries(RECENT_SORT_LABELS) as [RecentSort, string][]).map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>

      <select
        value={contentType}
        onChange={(e) => onContentTypeChange(e.target.value)}
        className={selectCls}
        aria-label="Content type"
      >
        <option value="">All types</option>
        {CONTENT_TYPE_OPTIONS.map((t) => (
          <option key={t} value={t}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </option>
        ))}
      </select>

      <select
        value={genre}
        onChange={(e) => onGenreChange(e.target.value)}
        className={selectCls}
        aria-label="Genre"
      >
        <option value="">All genres</option>
        {genreOptions.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </select>

      <select
        value={limit}
        onChange={(e) => onLimitChange(Number(e.target.value))}
        className={selectCls}
        aria-label="Number of cards"
      >
        {CARD_COUNT_OPTIONS.map((n) => (
          <option key={n} value={n}>
            {n} cards
          </option>
        ))}
      </select>
    </div>
  )
}
