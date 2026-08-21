import { EpisodeFixButtons } from '@/components/EpisodeFixButtons'
import type { EpisodeList } from '@/types/api'

export function TrackedBadges({
  ep,
  onFix,
  onFixEps,
  fixMatchDisabled,
}: {
  ep: EpisodeList
  onFix: (fileId?: number) => void
  onFixEps: (fileId?: number) => void
  fixMatchDisabled?: boolean
}) {
  if (ep.backing_files.length > 0) {
    return (
      <div className="flex flex-col items-end gap-1 shrink-0">
        {ep.backing_files.map((bf) => (
          <EpisodeFixButtons
            key={bf.id}
            onFix={() => onFix(bf.id)}
            onFixEps={() => onFixEps(bf.id)}
            fixMatchDisabled={fixMatchDisabled}
          />
        ))}
      </div>
    )
  }

  if (ep.tracked_source === 'import') {
    // Import episodes have no DownloadedFile backing — begin-rematch returns 422
    // for them, so "Fix Match" is not available. Only "Fix Eps" applies.
    return (
      <button
        onClick={() => onFixEps()}
        className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 hover:bg-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:hover:bg-blue-900/60 shrink-0"
      >
        Fix Eps
      </button>
    )
  }

  return (
    <EpisodeFixButtons
      onFix={() => onFix()}
      onFixEps={() => onFixEps()}
      fixMatchDisabled={fixMatchDisabled}
    />
  )
}
