import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useCalendarWeek } from '@/hooks/useCalendar'
import { useDebounce } from '@/hooks/useDebounce'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { Button } from '@/components/ui/Button'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import {
  ANCHOR_MODE_OPTIONS,
  DEFAULT_CALENDAR_RANGE,
  GRID_COLS_CLASS,
  RANGE_LENGTH_OPTIONS,
  WEEK_START_DAY_OPTIONS,
  addDays,
  computeRangeStart,
  dayLabel,
  resolveAnchorMode,
  toISODate,
  type AnchorMode,
  type CalendarRangeSettings,
  type RangeLength,
  type WeekStartDay,
} from '@/utils/calendarRange'
import type { CalendarEpisode } from '@/types/api'

const TMDB_IMG = '/api/images/w92'

const STATUS_STYLE: Record<CalendarEpisode['status'], { dot: string; label: string }> = {
  tracked: { dot: 'bg-green-500', label: 'Aired — file tracked' },
  missing: { dot: 'bg-red-500', label: 'Aired — no file tracked' },
  upcoming: { dot: 'bg-gray-400', label: 'Upcoming' },
}

interface CalendarFilterState {
  filterContentType: string
  filterGenre: string
  query: string
}

const DEFAULT_CALENDAR_FILTERS: CalendarFilterState = {
  filterContentType: '',
  filterGenre: '',
  query: '',
}

function applyFilters(
  episodes: CalendarEpisode[],
  contentType: string,
  genre: string,
  query: string,
): CalendarEpisode[] {
  const q = query.trim().toLowerCase()
  return episodes.filter((ep) => {
    if (contentType && ep.content_type !== contentType) return false
    if (genre && !ep.genres?.some((g) => g.name === genre)) return false
    if (q && !ep.show_title.toLowerCase().includes(q)) return false
    return true
  })
}

function EpisodeCell({ episode }: { episode: CalendarEpisode }) {
  const status = STATUS_STYLE[episode.status]
  return (
    <Link
      to={`/shows/${episode.show_id}`}
      className="flex items-start gap-2 bg-white dark:bg-gray-900 rounded-lg shadow-sm p-2 hover:shadow transition-shadow"
    >
      {episode.poster_path ? (
        <img
          src={`${TMDB_IMG}${episode.poster_path}`}
          alt={episode.show_title}
          className="w-8 h-12 object-cover rounded flex-shrink-0"
          loading="lazy"
        />
      ) : (
        <div className="w-8 h-12 bg-gray-100 dark:bg-gray-800 rounded flex-shrink-0" />
      )}
      <div className="min-w-0">
        <p className="text-xs font-semibold line-clamp-2 dark:text-gray-100">{episode.show_title}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          S{String(episode.season_number).padStart(2, '0')}E
          {String(episode.episode_number).padStart(2, '0')}
        </p>
        <span
          className={`inline-block w-2 h-2 rounded-full mt-1 ${status.dot}`}
          title={status.label}
        />
      </div>
    </Link>
  )
}

export default function Calendar() {
  // Persisted so range/anchor choices survive navigating away and back, not
  // just page reloads — same pattern as the filters below, under its own key
  // so the two settings don't interfere with each other.
  const [rangeSettings, setRangeSettings] = useLocalStorageState<CalendarRangeSettings>(
    'jidou:calendar-range',
    DEFAULT_CALENDAR_RANGE,
  )
  const [rangeStart, setRangeStart] = useState(() => computeRangeStart(new Date(), rangeSettings))

  function setRangeLength(rangeLength: RangeLength) {
    const next = {
      ...rangeSettings,
      rangeLength,
      anchorMode: resolveAnchorMode(rangeSettings.anchorMode, rangeLength),
    }
    setRangeSettings(next)
    setRangeStart(computeRangeStart(new Date(), next))
  }

  function setAnchorMode(anchorMode: AnchorMode) {
    const next = { ...rangeSettings, anchorMode }
    setRangeSettings(next)
    setRangeStart(computeRangeStart(new Date(), next))
  }

  function setWeekStartDay(weekStartDay: WeekStartDay) {
    const next = { ...rangeSettings, weekStartDay }
    setRangeSettings(next)
    setRangeStart(computeRangeStart(new Date(), next))
  }

  // Persisted so filter choices survive navigating away and back, not just
  // page reloads — matches the Shows page's filter-persistence behavior.
  const [filters, setFilters] = useLocalStorageState<CalendarFilterState>(
    'jidou:calendar-filters',
    DEFAULT_CALENDAR_FILTERS,
  )
  const { filterContentType, filterGenre, query } = filters
  const setFilterContentType = (v: string) => setFilters({ ...filters, filterContentType: v })
  const setFilterGenre = (v: string) => setFilters({ ...filters, filterGenre: v })
  const setQuery = (v: string) => setFilters({ ...filters, query: v })
  const debouncedQuery = useDebounce(query, 300)

  const days = useMemo(
    () => Array.from({ length: rangeSettings.rangeLength }, (_, i) => addDays(rangeStart, i)),
    [rangeStart, rangeSettings.rangeLength],
  )
  const start = toISODate(days[0])
  const end = toISODate(days[days.length - 1])
  const today = toISODate(new Date())

  const { data: episodes = [], isLoading, isError, error } = useCalendarWeek(start, end, today)

  const genreOptions = useMemo(() => {
    const names = new Set<string>()
    episodes.forEach((ep) => ep.genres?.forEach((g) => { if (g.name) names.add(g.name) }))
    return Array.from(names).sort()
  }, [episodes])

  const filtered = useMemo(
    () => applyFilters(episodes, filterContentType, filterGenre, debouncedQuery),
    [episodes, filterContentType, filterGenre, debouncedQuery],
  )

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEpisode[]>()
    for (const ep of filtered) {
      const list = map.get(ep.air_date) ?? []
      list.push(ep)
      map.set(ep.air_date, list)
    }
    return map
  }, [filtered])

  const activeFilterCount = [filterContentType, filterGenre, query].filter(Boolean).length

  function clearFilters() {
    setFilters(DEFAULT_CALENDAR_FILTERS)
  }

  const selectCls = 'border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100'

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold mr-auto dark:text-gray-100">Calendar</h1>
        <button
          onClick={() => setRangeStart((s) => addDays(s, -rangeSettings.rangeLength))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:bg-gray-800"
        >
          ← Prev
        </button>
        <button
          onClick={() => setRangeStart(computeRangeStart(new Date(), rangeSettings))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:bg-gray-800"
        >
          Today
        </button>
        <button
          onClick={() => setRangeStart((s) => addDays(s, rangeSettings.rangeLength))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:hover:bg-gray-800"
        >
          Next →
        </button>
      </div>

      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Range</span>
          <SegmentedControl
            aria-label="Range length"
            options={RANGE_LENGTH_OPTIONS}
            value={rangeSettings.rangeLength}
            onChange={setRangeLength}
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Anchor</span>
          <SegmentedControl
            aria-label="Anchor mode"
            options={ANCHOR_MODE_OPTIONS.map((o) => ({
              ...o,
              disabled: o.value === 'week-start' && rangeSettings.rangeLength !== 7,
              disabledReason:
                o.value === 'week-start' && rangeSettings.rangeLength !== 7
                  ? 'Only available for 7-day range'
                  : undefined,
            }))}
            value={rangeSettings.anchorMode}
            onChange={setAnchorMode}
          />
        </div>
        {rangeSettings.anchorMode === 'week-start' && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500 dark:text-gray-400">Week begins</span>
            <SegmentedControl
              aria-label="Week start day"
              options={WEEK_START_DAY_OPTIONS}
              value={rangeSettings.weekStartDay}
              onChange={setWeekStartDay}
            />
          </div>
        )}
      </div>

      <div className="flex items-center gap-3 flex-wrap bg-gray-50 dark:bg-gray-900 border rounded-lg px-4 py-3">
        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 shrink-0">Filter</span>

        <input
          type="search"
          placeholder="Search shows…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border rounded px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
        />

        <select value={filterContentType} onChange={(e) => setFilterContentType(e.target.value)} className={selectCls}>
          <option value="">All types</option>
          <option value="anime">Anime</option>
          <option value="tv">TV</option>
          <option value="movie">Movie</option>
        </select>

        {genreOptions.length > 0 && (
          <select value={filterGenre} onChange={(e) => setFilterGenre(e.target.value)} className={selectCls}>
            <option value="">All genres</option>
            {genreOptions.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        )}

        {activeFilterCount > 0 && (
          <Button onClick={clearFilters} variant="secondary" tone="light" size="sm">
            Clear filters ({activeFilterCount})
          </Button>
        )}
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400">
        {start} – {end}
        {activeFilterCount > 0 && ` · ${filtered.length} of ${episodes.length} episodes`}
      </p>

      {isError ? (
        <p className="text-sm text-red-600 dark:text-red-400">
          Failed to load the calendar{error instanceof Error ? `: ${error.message}` : ''}.
        </p>
      ) : isLoading ? (
        <p className="text-sm text-gray-400 dark:text-gray-500">Loading…</p>
      ) : activeFilterCount > 0 && filtered.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">No episodes in this range match the current filters.</p>
      ) : (
        <div className={GRID_COLS_CLASS[rangeSettings.rangeLength]}>
          {days.map((day) => {
            const iso = toISODate(day)
            const dayEpisodes = byDay.get(iso) ?? []
            const isToday = iso === today
            return (
              <div key={iso} className="space-y-2">
                <div
                  className={`text-xs font-semibold px-2 py-1 rounded ${
                    isToday ? 'bg-[var(--color-ocean-500)] text-white' : 'text-gray-500 dark:text-gray-400'
                  }`}
                >
                  {dayLabel(day)} {day.getMonth() + 1}/{day.getDate()}
                </div>
                <div className="space-y-2">
                  {dayEpisodes.length === 0 ? (
                    <p className="text-xs text-gray-300 dark:text-gray-700 px-2">—</p>
                  ) : (
                    dayEpisodes.map((ep) => <EpisodeCell key={ep.episode_id} episode={ep} />)
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
