interface Props {
  watched: number
  total: number
  showLabel?: boolean
  className?: string
  trackClassName?: string
  barClassName?: string
}

export function WatchedProgressBar({
  watched,
  total,
  showLabel = false,
  className = '',
  trackClassName = 'h-1.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700',
  barClassName = 'h-full rounded-full bg-green-500',
}: Props) {
  if (total === 0) return null
  const pct = Math.min(100, Math.round((watched / total) * 100))

  return (
    <div className={className}>
      {showLabel && (
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
          {watched} / {total} watched
        </p>
      )}
      <div className={trackClassName}>
        <div className={`transition-[width] ${barClassName}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
