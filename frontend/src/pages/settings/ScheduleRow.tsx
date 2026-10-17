import clsx from 'clsx'

/** One read-only schedule line: enabled badge, label, the daily UTC hours and the next run. */
export function ScheduleRow({ label, enabled, hours }: { label: string; enabled: boolean; hours: string }) {
  const nextRun = enabled ? computeNextRun(hours) : null
  const parsedHours = hours
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean)
    .map((h) => `${h.padStart(2, '0')}:00`)
    .join(', ')

  return (
    <div className="flex items-center gap-3 text-sm">
      <span
        className={clsx(
          'text-xs font-medium px-2 py-0.5 rounded-full shrink-0',
          enabled ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
        )}
      >
        {enabled ? 'Enabled' : 'Disabled'}
      </span>
      <span className="w-32 text-gray-700 dark:text-gray-300 shrink-0">{label}</span>
      {enabled ? (
        <>
          <span className="text-xs text-gray-500 dark:text-gray-400 flex-1">Daily at {parsedHours} UTC</span>
          <span className="text-xs text-gray-400 dark:text-gray-500 shrink-0">
            Next: {nextRun ? nextRun.toLocaleString(undefined, { timeZoneName: 'short' }) : '—'}
          </span>
        </>
      ) : (
        <span className="text-xs text-gray-400 dark:text-gray-500 italic flex-1">not scheduled</span>
      )}
    </div>
  )
}

function computeNextRun(hoursStr: string): Date | null {
  const hours = hoursStr
    .split(',')
    .map((h) => parseInt(h.trim(), 10))
    .filter((h) => !isNaN(h) && h >= 0 && h <= 23)
    .sort((a, b) => a - b)
  if (hours.length === 0) return null

  const now = new Date()
  const nowUtcHour = now.getUTCHours()

  const nextHour = hours.find((h) => h > nowUtcHour)
  const next = new Date()
  if (nextHour !== undefined) {
    next.setUTCHours(nextHour, 0, 0, 0)
  } else {
    next.setUTCDate(next.getUTCDate() + 1)
    next.setUTCHours(hours[0], 0, 0, 0)
  }
  return next
}
