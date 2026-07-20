import { RECENT_SORT_LABELS, type RecentSort } from '@/hooks/useDashboard'

const CARD_COUNT_OPTIONS = [6, 12, 18, 24, 36]
const DEFAULT_CONTENT_TYPE_OPTIONS = ['anime', 'tv', 'movie']

interface Props {
  sort: RecentSort
  onSortChange: (sort: RecentSort) => void
  genre: string
  onGenreChange: (genre: string) => void
  genreOptions: string[]
  // Omit both to hide the content-type select entirely — used by sections
  // that are already scoped to a single content type (e.g. movies), where
  // the filter would always be redundant.
  contentType?: string
  onContentTypeChange?: (contentType: string) => void
  contentTypeOptions?: string[]
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
  // Defaulted so the <select> below is always controlled, even before a
  // caller that omits contentType entirely (it's only meaningful paired
  // with onContentTypeChange) ever renders it.
  contentType = '',
  onContentTypeChange,
  contentTypeOptions = DEFAULT_CONTENT_TYPE_OPTIONS,
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

      {onContentTypeChange && (
        <select
          value={contentType}
          onChange={(e) => onContentTypeChange(e.target.value)}
          className={selectCls}
          aria-label="Content type"
        >
          <option value="">All types</option>
          {contentTypeOptions.map((t) => (
            <option key={t} value={t}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </option>
          ))}
        </select>
      )}

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
