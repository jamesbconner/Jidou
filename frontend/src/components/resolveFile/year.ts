/** Four-digit year of an ISO date string, or null when the date is missing. */
export function year(date: string | null | undefined): string | null {
  return date ? new Date(date).getFullYear().toString() : null
}
