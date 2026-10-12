import { toHostPath, toContainerPath } from '@/utils/paths'
import type {
  ContentType,
  FileRead,
  MediaPaths,
  ShowSearchResult,
  TmdbResult,
} from '@/types/api'

/**
 * Presentational panes of RematchModal.
 *
 * The modal keeps every query, mutation and typed value; these only render what
 * they are handed, so request timing and retained input are unchanged.
 */

const TMDB_IMAGE_BASE = '/api/images/w300'

export type RematchMode = 'library' | 'tmdb'

/** The library show a TMDB result already maps to, when there is one. */
export interface LibraryMatch {
  id: number
  local_path?: string | null
}

/** Filename plus the show the file is currently assigned to. */
export function FileSummary({ file }: { file: FileRead }) {
  return (
    <div className="bg-zinc-800 rounded p-3 space-y-1">
      <div className="text-xs text-zinc-400">File</div>
      <div className="font-mono text-xs text-zinc-200 truncate">{file.original_filename}</div>
      {file.show_id && (
        <div className="text-xs text-zinc-500 mt-0.5">Currently assigned to {file.show?.title ?? `show #${file.show_id}`}</div>
      )}
    </div>
  )
}

/** Library / TMDB toggle. */
export function ModeToggle({ mode, onChange }: { mode: RematchMode; onChange: (mode: RematchMode) => void }) {
  return (
    <div className="flex gap-1 bg-zinc-800 rounded p-1">
      {(['library', 'tmdb'] as const).map((m) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          className={`flex-1 text-xs py-1.5 rounded transition-colors font-medium ${
            mode === m ? 'bg-[var(--color-ocean-600)] text-white' : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          {m === 'library' ? 'Library' : 'TMDB'}
        </button>
      ))}
    </div>
  )
}

interface LibraryResultsPaneProps {
  results: ShowSearchResult[]
  selected: ShowSearchResult | null
  onSelect: (show: ShowSearchResult) => void
  mediaPaths: MediaPaths | undefined
  showNoResults: boolean
}

/** Library search hits with their folders, plus the no-path warning for the pick. */
export function LibraryResultsPane({
  results,
  selected,
  onSelect,
  mediaPaths,
  showNoResults,
}: LibraryResultsPaneProps) {
  return (
    <div className="space-y-1.5">
      {results.map((s) => (
        <button
          key={s.id}
          onClick={() => onSelect(s)}
          className={`w-full text-left px-3 py-2 rounded border text-xs transition-colors ${
            selected?.id === s.id
              ? 'border-[var(--color-ocean-500)] bg-[var(--color-ocean-950)]/50'
              : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
          }`}
        >
          <div className="font-medium text-zinc-200">{s.title}</div>
          <div className="text-zinc-500">
            #{s.id}
            {s.local_path
              ? ` · ${mediaPaths ? toHostPath(s.local_path, mediaPaths) : s.local_path}`
              : ' · no local path set'}
          </div>
        </button>
      ))}
      {showNoResults && (
        <div className="text-xs text-zinc-500 py-1">No library shows found.</div>
      )}
      {selected && !selected.local_path && (
        <div className="text-xs text-yellow-400 bg-yellow-950/30 border border-yellow-800/40 rounded p-2 mt-1">
          This show has no local path — set one on the show detail page first.
        </div>
      )}
    </div>
  )
}

/** Poster grid of TMDB search results. */
export function TmdbGrid({
  results,
  selected,
  onSelect,
}: {
  results: TmdbResult[]
  selected: TmdbResult | null
  onSelect: (result: TmdbResult) => void
}) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {results.map((r) => (
        <button
          key={`${r.id}-${r.media_type}`}
          onClick={() => onSelect(r)}
          className={`flex flex-col rounded border text-left overflow-hidden transition-colors ${
            selected?.id === r.id && selected?.media_type === r.media_type
              ? 'border-[var(--color-ocean-500)] bg-[var(--color-ocean-950)]/50'
              : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
          }`}
        >
          {r.poster_path ? (
            <img
              src={`${TMDB_IMAGE_BASE}${r.poster_path}`}
              alt={r.name ?? r.title ?? ''}
              className="w-full aspect-[2/3] object-cover"
            />
          ) : (
            <div className="w-full aspect-[2/3] bg-zinc-700 flex items-center justify-center text-zinc-500 text-xs">
              No image
            </div>
          )}
          <div className="p-2 space-y-0.5">
            <div className="text-xs font-medium text-zinc-200 line-clamp-2 leading-tight">
              {r.name ?? r.title}
            </div>
            <div className="text-xs text-zinc-500">
              {(r.first_air_date ?? r.release_date)?.slice(0, 4)} · {r.media_type}
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}

/** Wording for the library-status line of a selected TMDB result. */
function libraryStatusText(existing: LibraryMatch | undefined): string {
  if (!existing) return 'Not in library — will create a new show'
  if (existing.local_path != null) {
    return `Already in library as show #${existing.id} — will use existing record`
  }
  return `Already in library as show #${existing.id} — no local path set, configure it in Shows first`
}

interface NewShowFieldsProps {
  contentType: ContentType
  onContentTypeChange: (type: ContentType) => void
  folderName: string
  onFolderNameChange: (value: string) => void
  mediaPaths: MediaPaths | undefined
}

/** Content type radios and folder-name input used when the show will be created. */
function NewShowFields({
  contentType,
  onContentTypeChange,
  folderName,
  onFolderNameChange,
  mediaPaths,
}: NewShowFieldsProps) {
  return (
    <>
      <div className="space-y-1.5">
        <div className="text-xs text-zinc-400">Content type</div>
        <div className="flex gap-4">
          {(['anime', 'tv', 'movie'] as ContentType[]).map((t) => (
            <label
              key={t}
              className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer"
            >
              <input
                type="radio"
                name="rematch_content_type"
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
      <div className="space-y-1">
        <div className="text-xs text-zinc-400">Show folder name</div>
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
      </div>
    </>
  )
}

/** Library status of the selected TMDB result and, for a new show, its folder fields. */
export function TmdbSelectionDetails({
  existing,
  ...fields
}: { existing: LibraryMatch | undefined } & NewShowFieldsProps) {
  return (
    <div className="border border-zinc-700 rounded p-3 space-y-3">
      <div className={`text-xs font-medium ${existing && existing.local_path == null ? 'text-amber-400' : 'text-zinc-300'}`}>
        {libraryStatusText(existing)}
      </div>
      {!existing && <NewShowFields {...fields} />}
    </div>
  )
}
