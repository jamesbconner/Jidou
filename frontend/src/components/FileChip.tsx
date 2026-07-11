export function FileChip({
  label,
  chipClass,
  onFix,
  onFixEps,
  fixMatchDisabled,
}: {
  label: string
  chipClass: string
  onFix: () => void
  onFixEps: () => void
  fixMatchDisabled?: boolean
}) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${chipClass}`}>
        {label}
      </span>
      <button
        onClick={onFix}
        disabled={fixMatchDisabled}
        className="text-xs text-blue-600 hover:underline disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Fix Match
      </button>
      <button
        onClick={onFixEps}
        className="text-xs text-blue-600 hover:underline"
      >
        Fix Eps
      </button>
    </div>
  )
}
