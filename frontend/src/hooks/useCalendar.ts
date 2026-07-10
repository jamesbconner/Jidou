import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { CalendarEpisode } from '@/types/api'

export const calendarKeys = {
  all: ['calendar'] as const,
  week: (start: string, end: string, today: string) =>
    [...calendarKeys.all, start, end, today] as const,
}

// `today` is the browser's local date, not the API host's — the backend
// uses it to decide "tracked"/"missing" vs "upcoming", and must agree with
// whichever day the UI highlights as "today" or the two can disagree
// across a timezone or day-boundary difference between client and server.
export function useCalendarWeek(start: string, end: string, today: string) {
  return useQuery({
    queryKey: calendarKeys.week(start, end, today),
    queryFn: () =>
      api.get<CalendarEpisode[]>(`/shows/calendar?start=${start}&end=${end}&today=${today}`),
  })
}
