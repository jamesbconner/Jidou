export type RangeLength = 1 | 3 | 5 | 7
export type AnchorMode = 'today-start' | 'today-centered' | 'week-start'
export type WeekStartDay = 'sunday' | 'monday'

export interface CalendarRangeSettings {
  rangeLength: RangeLength
  anchorMode: AnchorMode
  weekStartDay: WeekStartDay
}

// Reproduces the calendar's original hardcoded behavior (7-day, Monday-start
// week) so existing users see no visual change until they customize.
export const DEFAULT_CALENDAR_RANGE: CalendarRangeSettings = {
  rangeLength: 7,
  anchorMode: 'week-start',
  weekStartDay: 'monday',
}

export const RANGE_LENGTH_OPTIONS: { value: RangeLength; label: string }[] = [
  { value: 1, label: '1' },
  { value: 3, label: '3' },
  { value: 5, label: '5' },
  { value: 7, label: '7' },
]

export const ANCHOR_MODE_OPTIONS: { value: AnchorMode; label: string }[] = [
  { value: 'today-start', label: 'Today start' },
  { value: 'today-centered', label: 'Centered' },
  { value: 'week-start', label: 'Week start' },
]

export const WEEK_START_DAY_OPTIONS: { value: WeekStartDay; label: string }[] = [
  { value: 'sunday', label: 'Sun' },
  { value: 'monday', label: 'Mon' },
]

// Tailwind's JIT compiler only picks up class names it can find as literal
// strings in source, so the column count must be a static lookup rather than
// a dynamically constructed class string.
export const GRID_COLS_CLASS: Record<RangeLength, string> = {
  1: 'grid grid-cols-1 gap-3',
  3: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3',
  5: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3',
  7: 'grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7 gap-3',
}

const DAY_ABBR = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

export function toISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function addDays(d: Date, n: number): Date {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + n)
  return copy
}

function startOfDay(d: Date): Date {
  const copy = new Date(d)
  copy.setHours(0, 0, 0, 0)
  return copy
}

export function startOfWeek(d: Date, weekStartDay: WeekStartDay): Date {
  const day = d.getDay() // 0 = Sunday
  const offset = weekStartDay === 'monday' ? (day + 6) % 7 : day
  return startOfDay(addDays(d, -offset))
}

export function dayLabel(d: Date): string {
  return DAY_ABBR[d.getDay()]
}

// "week-start" only makes sense for a full 7-day range; anything else falls
// back to "today-start" so the UI never ends up in an invalid combination.
export function resolveAnchorMode(anchorMode: AnchorMode, rangeLength: RangeLength): AnchorMode {
  if (anchorMode === 'week-start' && rangeLength !== 7) return 'today-start'
  return anchorMode
}

// The single entry point for (re)anchoring the displayed window on `today`
// under the given settings — used both for initial render and any time a
// range/anchor setting changes.
export function computeRangeStart(today: Date, settings: CalendarRangeSettings): Date {
  const { rangeLength, weekStartDay } = settings
  switch (resolveAnchorMode(settings.anchorMode, rangeLength)) {
    case 'today-centered':
      return addDays(startOfDay(today), -Math.floor(rangeLength / 2))
    case 'week-start':
      return startOfWeek(today, weekStartDay)
    case 'today-start':
    default:
      return startOfDay(today)
  }
}
