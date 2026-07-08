import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { CalendarEpisode } from '@/types/api'

export const calendarKeys = {
  all: ['calendar'] as const,
  week: (start: string, end: string) => [...calendarKeys.all, start, end] as const,
}

export function useCalendarWeek(start: string, end: string) {
  return useQuery({
    queryKey: calendarKeys.week(start, end),
    queryFn: () => api.get<CalendarEpisode[]>(`/shows/calendar?start=${start}&end=${end}`),
  })
}
