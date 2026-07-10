import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCalendarWeek } from '@/hooks/useCalendar'
import type { CalendarEpisode } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w92'

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const STATUS_STYLE: Record<CalendarEpisode['status'], { dot: string; label: string }> = {
  tracked: { dot: 'bg-green-500', label: 'Aired — file tracked' },
  missing: { dot: 'bg-red-500', label: 'Aired — no file tracked' },
  upcoming: { dot: 'bg-gray-400', label: 'Upcoming' },
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

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )
  const start = toISODate(days[0])
  const end = toISODate(days[6])
  const today = toISODate(new Date())

  const { data: episodes = [], isLoading, isError, error } = useCalendarWeek(start, end, today)

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEpisode[]>()
    for (const ep of episodes) {
      const list = map.get(ep.air_date) ?? []
      list.push(ep)
      map.set(ep.air_date, list)
    }
    return map
  }, [episodes])

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

      <p className="text-sm text-gray-500">
        {start} – {end}
      </p>

      {isError ? (
        <p className="text-sm text-red-600">
          Failed to load the calendar{error instanceof Error ? `: ${error.message}` : ''}.
        </p>
      ) : isLoading ? (
        <p className="text-sm text-gray-400">Loading…</p>
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
