/**
 * Four-digit year of an ISO date string, or null when the date is missing.
 *
 * Read in UTC: `new Date("2020-01-01")` is UTC midnight, so the local-time
 * getter would report 2019 anywhere west of UTC.
 */
export function year(date: string | null | undefined): string | null {
  return date ? new Date(date).getUTCFullYear().toString() : null
}
