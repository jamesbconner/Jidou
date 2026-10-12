import { year } from '@/components/resolveFile/year'
import type { SearchMode } from '@/components/resolveFile/useResolveCandidates'
import { toHostPath } from '@/utils/paths'
import type { FileRead, MediaPaths, ShowSearchResult } from '@/types/api'

/**
 * Presentational sections of ResolveFileModal.
 *
 * All state, queries and mutations stay in the modal; these only render what
 * they are given, so request timing and retained input are unchanged.
 */

/** A show already in the local library that this file can be assigned to. */
export interface ExistingShow {
  id: number
  title: string
  local_path?: string | null
}

/** Label describing why a library hit matched when it was not by title. */
function matchedOnLabel(matchedOn: string): string {
  if (matchedOn === 'path') return 'folder'
  if (matchedOn === 'sys_name') return 'system name'
  return 'alias'
}

/** Resolves a container path to a host path once the media-path config is loaded. */
function displayPath(path: string, mediaPaths: MediaPaths | undefined): string {
  return mediaPaths ? toHostPath(path, mediaPaths) : path
}

/** Filename and parsed-name summary at the top of the modal. */
export function FileInfo({ file }: { file: FileRead }) {
  return (
    <div className="bg-zinc-800 rounded p-3 space-y-1">
      <div className="text-xs text-zinc-400">Filename</div>
      <div className="font-mono text-xs text-zinc-200 truncate">{file.original_filename}</div>
      {file.parsed_show_name && (
        <>
          <div className="text-xs text-zinc-400 mt-1">Parsed as</div>
          <div className="text-xs text-zinc-300">{file.parsed_show_name}</div>
        </>
      )}
    </div>
  )
}

interface LocalCandidate {
  key: string
  local?: ShowSearchResult | null
}

/** "In your library" list of local shows the file can be assigned to. */
export function LocalMatches({
  loading,
  candidates,
  selectedId,
  mediaPaths,
  onSelect,
}: {
  loading: boolean
  candidates: LocalCandidate[]
  selectedId: number | undefined
  mediaPaths: MediaPaths | undefined
  onSelect: (show: ShowSearchResult) => void
}) {
  if (!loading && candidates.length === 0) return null
  return (
    <div className="space-y-2">
      <div className="text-xs text-zinc-400">In your library</div>
      {loading && candidates.length === 0 && (
        <div className="text-xs text-zinc-500 py-1">Searching library…</div>
      )}
      <div className="space-y-1.5">
        {candidates.map(
          ({ key, local: s }) =>
            s && (
              <button
                key={key}
                onClick={() => onSelect(s)}
                className={`w-full flex items-center gap-3 rounded border px-3 py-2 text-left transition-colors ${
                  selectedId === s.id
                    ? 'border-[var(--color-ocean-500)] bg-[var(--color-ocean-950)]/50'
                    : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-zinc-200 truncate">
                    {s.title}
                    {year(s.release_date) ? ` (${year(s.release_date)})` : ''}
                  </div>
                  <div className="text-xs text-zinc-500 font-mono truncate">
                    {s.local_path ? displayPath(s.local_path, mediaPaths) : 'no local path set'}
                  </div>
                </div>
                {s.matched_on !== 'title' && (
                  <span className="text-[10px] uppercase tracking-wide text-zinc-400 shrink-0">
                    matched {matchedOnLabel(s.matched_on)}
                  </span>
                )}
              </button>
            ),
        )}
      </div>
    </div>
  )
}

interface SearchControlsProps {
  mode: SearchMode
  onRefine: () => void
  onSearchById: () => void
  onBackToSuggestions: () => void
  query: string
  onQueryChange: (value: string) => void
  tmdbIdQuery: string
  onTmdbIdQueryChange: (value: string) => void
  tmdbIdMediaType: 'tv' | 'movie'
  onTmdbIdMediaTypeChange: (value: 'tv' | 'movie') => void
}

/** Mode switch links plus the title or TMDB-id input for the active mode. */
export function SearchControls({
  mode,
  onRefine,
  onSearchById,
  onBackToSuggestions,
  query,
  onQueryChange,
  tmdbIdQuery,
  onTmdbIdQueryChange,
  tmdbIdMediaType,
  onTmdbIdMediaTypeChange,
}: SearchControlsProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <label className="text-xs text-zinc-400">Search TMDB</label>
        {mode === 'suggestions' ? (
          <>
            <button
              onClick={onRefine}
              className="text-xs text-[var(--color-ocean-400)] hover:text-[var(--color-ocean-300)]"
            >
              refine search
            </button>
            <button
              onClick={onSearchById}
              className="text-xs text-[var(--color-ocean-400)] hover:text-[var(--color-ocean-300)]"
            >
              search by TMDB ID
            </button>
          </>
        ) : (
          <button
            onClick={onBackToSuggestions}
            className="text-xs text-zinc-500 hover:text-zinc-300"
          >
            back to suggestions
          </button>
        )}
      </div>
      {mode === 'title' && (
        <input
          type="text"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search TMDB..."
          className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
        />
      )}
      {mode === 'tmdb_id' && (
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            value={tmdbIdQuery}
            onChange={(e) => onTmdbIdQueryChange(e.target.value)}
            placeholder="TMDB ID, e.g. 1668"
            className="flex-1 bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
          />
          <select
            value={tmdbIdMediaType}
            onChange={(e) => onTmdbIdMediaTypeChange(e.target.value as 'tv' | 'movie')}
            className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-[var(--color-ocean-500)]"
          >
            <option value="tv">TV</option>
            <option value="movie">Movie</option>
          </select>
        </div>
      )}
    </div>
  )
}

/** Summary of the existing library show the file will be assigned to. */
export function ExistingShowPanel({
  existing,
  fromLibraryPick,
  title,
  yearText,
  mediaPaths,
}: {
  existing: ExistingShow
  /** True when the show was picked directly from the library list. */
  fromLibraryPick: boolean
  title: string | null
  yearText: string | null | undefined
  mediaPaths: MediaPaths | undefined
}) {
  return (
    <div className="border border-zinc-700 rounded p-3 space-y-2">
      <div className="text-xs font-medium text-zinc-300">
        Selected: {title}
        {yearText ? ` (${yearText})` : ''}
      </div>
      <div className="text-xs text-emerald-400">
        {fromLibraryPick
          ? 'In your library — the file will be assigned to this show.'
          : `Already in your library as "${existing.title}" — the file will be assigned to it.`}
      </div>
      {existing.local_path ? (
        <div className="space-y-1">
          <div className="text-xs text-zinc-400">Existing show folder</div>
          <div className="text-xs text-zinc-300 font-mono break-all">
            {displayPath(existing.local_path, mediaPaths)}
          </div>
          <div className="text-xs text-zinc-500">
            Files will be placed in Season NN/ subdirectories under this folder.
          </div>
        </div>
      ) : (
        <div className="text-xs text-amber-400">
          This show has no local path — set one on the show detail page first.
        </div>
      )}
    </div>
  )
}
