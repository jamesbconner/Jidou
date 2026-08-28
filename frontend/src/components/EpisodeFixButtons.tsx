export function EpisodeFixButtons({
  onFix,
  onFixEps,
  fixMatchDisabled,
}: {
  onFix: () => void
  onFixEps: () => void
  fixMatchDisabled?: boolean
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      <button
        onClick={onFix}
        disabled={fixMatchDisabled}
        className="px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-950)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/60 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Fix Match
      </button>
      <button
        onClick={onFixEps}
        className="px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] hover:bg-[var(--color-ocean-200)] dark:bg-[var(--color-ocean-950)]/40 dark:text-[var(--color-ocean-300)] dark:hover:bg-[var(--color-ocean-900)]/60"
      >
        Fix Eps
      </button>
    </div>
  )
}
