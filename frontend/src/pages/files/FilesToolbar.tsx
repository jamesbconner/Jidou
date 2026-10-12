import type { FileStatus } from '@/types/api'

const STATUS_OPTIONS: (FileStatus | '')[] = [
  '',
  'pending',
  'discovered',
  'downloading',
  'downloaded',
  'unmatched',
  'matched',
  'routing',
  'routed',
  'error',
  'seeded',
  'missing',
]

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
const MAX_RECORDS_OPTIONS = [50, 100, 200, 500, 1000]

interface FilesToolbarProps {
  search: string
  onSearchChange: (value: string) => void
  statusFilter: FileStatus | ''
  onStatusChange: (value: FileStatus | '') => void
  pageSize: number
  onPageSizeChange: (value: number) => void
  maxRecords: number | null
  onMaxRecordsChange: (value: number | null) => void
  showIgnored: boolean
  onShowIgnoredChange: (value: boolean) => void
  duplicatesOnly: boolean
  onDuplicatesOnlyChange: (value: boolean) => void
}

interface FilterSwitchProps {
  checked: boolean
  /** Accessible name while on (describes what clicking does). */
  onLabel: string
  /** Accessible name while off. */
  offLabel: string
  text: string
  onChange: (value: boolean) => void
}

/** A small on/off switch for a boolean list filter. */
function FilterSwitch({ checked, onLabel, offLabel, text, onChange }: FilterSwitchProps) {
  const label = checked ? onLabel : offLabel
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300"
    >
      <span
        className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors ${
          checked ? 'bg-[var(--color-ocean-600)]' : 'bg-gray-300 dark:bg-gray-700'
        }`}
      >
        <span
          className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-3.5' : 'translate-x-0.5'
          }`}
        />
      </span>
      {text}
    </button>
  )
}

/** Title row with the search box and the status / paging / ignored / duplicate filters. */
export function FilesToolbar({
  search,
  onSearchChange,
  statusFilter,
  onStatusChange,
  pageSize,
  onPageSizeChange,
  maxRecords,
  onMaxRecordsChange,
  showIgnored,
  onShowIgnoredChange,
  duplicatesOnly,
  onDuplicatesOnlyChange,
}: FilesToolbarProps) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <h1 className="text-2xl font-bold mr-auto dark:text-gray-100">Files</h1>
      <input
        type="search"
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
        placeholder="Search filenames…"
        className="border rounded-lg px-3 py-2 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
      />
      <select
        value={statusFilter}
        onChange={(e) => onStatusChange(e.target.value as FileStatus | '')}
        className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
      >
        {STATUS_OPTIONS.map((s) => (
          <option key={s} value={s}>{s || 'All statuses'}</option>
        ))}
      </select>
      <div>
        <label htmlFor="files-page-size" className="text-xs text-gray-500 dark:text-gray-400 mr-2">Per page</label>
        <select
          id="files-page-size"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="border rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="files-max-records" className="text-xs text-gray-500 dark:text-gray-400 mr-2">Max records</label>
        <select
          id="files-max-records"
          value={maxRecords === null ? 'all' : String(maxRecords)}
          onChange={(e) => onMaxRecordsChange(e.target.value === 'all' ? null : Number(e.target.value))}
          className="border rounded-lg px-2 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
        >
          {MAX_RECORDS_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
          <option value="all">All</option>
        </select>
      </div>
      <FilterSwitch
        checked={showIgnored}
        onLabel="Hide ignored files"
        offLabel="Show ignored files"
        text="Show ignored"
        onChange={onShowIgnoredChange}
      />
      <FilterSwitch
        checked={duplicatesOnly}
        onLabel="Show all files"
        offLabel="Show only duplicate files"
        text="Duplicates only"
        onChange={onDuplicatesOnlyChange}
      />
    </div>
  )
}
