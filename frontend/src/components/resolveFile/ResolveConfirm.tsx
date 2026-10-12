import { toContainerPath, toHostPath } from '@/utils/paths'
import type { ContentType, MediaPaths, TmdbSuggestion } from '@/types/api'
import { year } from './year'

interface Props {
  selected: TmdbSuggestion
  contentType: ContentType
  folderName: string
  /** Undefined until the app config has loaded; the path preview is hidden then. */
  mediaPaths: MediaPaths | undefined
  onContentTypeChange: (contentType: ContentType) => void
  onFolderNameChange: (folderName: string) => void
}

/**
 * Content-type and folder-name form for a TMDB pick that is not yet in the
 * library. Presentational: the modal keeps the form state and the rematch
 * mutation, because the footer buttons and error banner outside this block
 * share that mutation and its state must outlive a change of selection.
 */
export function ResolveConfirm({
  selected,
  contentType,
  folderName,
  mediaPaths,
  onContentTypeChange,
  onFolderNameChange,
}: Props) {
  return (
    <div className="border border-zinc-700 rounded p-3 space-y-3">
      <div className="text-xs font-medium text-zinc-300">
        Selected: {selected.title} ({year(selected.first_air_date)})
      </div>

      {/* Content type */}
      <div className="space-y-1">
        <label className="text-xs text-zinc-400">Content type</label>
        <div className="flex gap-3">
          {(['anime', 'tv', 'movie'] as ContentType[]).map((t) => (
            <label key={t} className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer">
              <input
                type="radio"
                name="content_type"
                value={t}
                checked={contentType === t}
                onChange={() => onContentTypeChange(t)}
                className="accent-[var(--color-ocean-500)]"
              />
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </label>
          ))}
        </div>
      </div>

      {/* Show folder name */}
      <div className="space-y-1">
        <label className="text-xs text-zinc-400">Show folder name</label>
        <input
          type="text"
          value={folderName}
          onChange={(e) => onFolderNameChange(e.target.value)}
          placeholder="Show Name"
          className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
        />
        {mediaPaths && folderName.trim() && (
          <div className="text-xs text-zinc-500 font-mono">
            {toHostPath(toContainerPath(contentType, folderName.trim(), mediaPaths), mediaPaths)}
          </div>
        )}
        {!folderName.trim() && (
          <div className="text-xs text-amber-400">
            This result has no title — enter a folder name above to continue.
          </div>
        )}
        <div className="text-xs text-zinc-500">
          Files will be placed in Season NN/ subdirectories under this folder.
        </div>
      </div>
    </div>
  )
}
