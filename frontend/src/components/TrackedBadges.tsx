import { FileChip } from '@/components/FileChip'
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
          <FileChip
            key={bf.id}
            label="Matched"
            chipClass="bg-teal-100 text-teal-700"
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
    // for them, so "Fix Match" is not available. Show only the badge + "Fix Eps".
    return (
      <div className="flex items-center gap-2 shrink-0">
        <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
          Imported
        </span>
        <button
          onClick={() => onFixEps()}
          className="text-xs text-blue-600 hover:underline"
        >
          Fix Eps
        </button>
      </div>
    )
  }

  return (
    <FileChip
      label="Tracked"
      chipClass="bg-teal-100 text-teal-700"
      onFix={() => onFix()}
      onFixEps={() => onFixEps()}
      fixMatchDisabled={fixMatchDisabled}
    />
  )
}
