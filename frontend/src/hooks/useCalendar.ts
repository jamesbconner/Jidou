import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { CalendarEpisode, CalendarSyncResult } from '@/types/api'

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

// Re-syncs TMDB metadata for every show behind a "missing" episode in
// [start, end] -- the same date range and `today` the calling view is
// showing, so the backend recomputes exactly the shows it's currently
// flagging missing. Manual, scoped alternative to the scheduled sync, which
// skips already-`cached` shows and so never revisits a schedule change TMDB
// makes after the first sync (see get_calendar's "missing" status).
export function useSyncMissingCalendarShows() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ start, end, today }: { start: string; end: string; today: string }) =>
      api.post<CalendarSyncResult>(
        `/shows/calendar/sync-missing?start=${start}&end=${end}&today=${today}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: calendarKeys.all })
    },
  })
}
