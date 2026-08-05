import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { useCalendarWeek } from '@/hooks/useCalendar'
import { useDebounce } from '@/hooks/useDebounce'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { Button } from '@/components/ui/Button'
import type { CalendarEpisode } from '@/types/api'

const TMDB_IMG = '/api/images/w92'

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

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

function toISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function mondayOf(d: Date): Date {
  const day = d.getDay() // 0 = Sunday
  const diff = day === 0 ? -6 : 1 - day
  const monday = new Date(d)
  monday.setDate(d.getDate() + diff)
  monday.setHours(0, 0, 0, 0)
  return monday
}

function addDays(d: Date, n: number): Date {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + n)
  return copy
}

function EpisodeCell({ episode }: { episode: CalendarEpisode }) {
  const status = STATUS_STYLE[episode.status]
  return (
    <Link
      to={`/shows/${episode.show_id}`}
      className="flex items-start gap-2 bg-white rounded-lg shadow-sm p-2 hover:shadow transition-shadow"
    >
      {episode.poster_path ? (
        <img
          src={`${TMDB_IMG}${episode.poster_path}`}
          alt={episode.show_title}
          className="w-8 h-12 object-cover rounded flex-shrink-0"
          loading="lazy"
        />
      ) : (
        <div className="w-8 h-12 bg-gray-100 rounded flex-shrink-0" />
      )}
      <div className="min-w-0">
        <p className="text-xs font-semibold line-clamp-2">{episode.show_title}</p>
        <p className="text-xs text-gray-500">
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
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()))

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
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )
  const start = toISODate(days[0])
  const end = toISODate(days[6])
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

  const selectCls = 'border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold mr-auto">Calendar</h1>
        <button
          onClick={() => setWeekStart((w) => addDays(w, -7))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          ← Prev
        </button>
        <button
          onClick={() => setWeekStart(mondayOf(new Date()))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Today
        </button>
        <button
          onClick={() => setWeekStart((w) => addDays(w, 7))}
          className="border rounded-lg px-3 py-2 text-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Next →
        </button>
      </div>

      <div className="flex items-center gap-3 flex-wrap bg-gray-50 border rounded-lg px-4 py-3">
        <span className="text-xs font-medium text-gray-500 shrink-0">Filter</span>

        <input
          type="search"
          placeholder="Search shows…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border rounded px-2 py-1 text-sm w-48 focus:outline-none focus:ring-2 focus:ring-blue-500"
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

      <p className="text-sm text-gray-500">
        {start} – {end}
        {activeFilterCount > 0 && ` · ${filtered.length} of ${episodes.length} episodes`}
      </p>

      {isError ? (
        <p className="text-sm text-red-600">
          Failed to load the calendar{error instanceof Error ? `: ${error.message}` : ''}.
        </p>
      ) : isLoading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : activeFilterCount > 0 && filtered.length === 0 ? (
        <p className="text-sm text-gray-500">No episodes this week match the current filters.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7 gap-3">
          {days.map((day, i) => {
            const iso = toISODate(day)
            const dayEpisodes = byDay.get(iso) ?? []
            const isToday = iso === today
            return (
              <div key={iso} className="space-y-2">
                <div
                  className={`text-xs font-semibold px-2 py-1 rounded ${
                    isToday ? 'bg-blue-500 text-white' : 'text-gray-500'
                  }`}
                >
                  {DAY_LABELS[i]} {day.getMonth() + 1}/{day.getDate()}
                </div>
                <div className="space-y-2">
                  {dayEpisodes.length === 0 ? (
                    <p className="text-xs text-gray-300 px-2">—</p>
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
