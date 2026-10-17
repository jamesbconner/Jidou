/**
 * Parse a comma-separated list of UTC schedule hours (e.g. "4,16").
 *
 * Mirrors the backend's `services/schedule_hours.py` so the form rejects what
 * the API would. Whitespace and empty entries are tolerated; each entry must be
 * a whole number from 0 to 23.
 *
 * @returns the distinct hours in ascending order, or `null` if any entry is
 *   invalid or no hour is given.
 */
export function parseScheduleHours(raw: string): number[] | null {
  const hours = new Set<number>()
  for (const part of raw.split(',')) {
    const segment = part.trim()
    if (segment === '') continue
    // ASCII digits only; \d would also accept other scripts' digits.
    if (!/^[0-9]+$/.test(segment)) return null
    const hour = Number(segment)
    if (hour < 0 || hour > 23) return null
    hours.add(hour)
  }
  if (hours.size === 0) return null
  return [...hours].sort((a, b) => a - b)
}

/** Canonical form of a valid hour list ("16, 04" -> "4,16"), or `null` if invalid. */
export function normalizeScheduleHours(raw: string): string | null {
  const hours = parseScheduleHours(raw)
  return hours === null ? null : hours.join(',')
}
