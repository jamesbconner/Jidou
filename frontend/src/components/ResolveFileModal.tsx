import { useState } from 'react'
import { useConfig } from '@/hooks/useConfig'
import { useRematchFile } from '@/hooks/useFiles'
import { useLibraryIndex } from '@/hooks/useShows'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { CandidateList } from '@/components/resolveFile/CandidateList'
import { ResolveConfirm } from '@/components/resolveFile/ResolveConfirm'
import {
  useResolveCandidates,
  type SearchMode,
} from '@/components/resolveFile/useResolveCandidates'
import { year } from '@/components/resolveFile/year'
import { toContainerPath, toHostPath, sanitizeFolderName } from '@/utils/paths'
import type { FileRead, TmdbSuggestion, ContentType, ShowSearchResult } from '@/types/api'

/** A show already in the local library that this file can be assigned to. */
interface ExistingShow {
  id: number
  title: string
  local_path?: string | null
}

interface Props {
  file: FileRead
  onClose: () => void
}

export function ResolveFileModal({ file, onClose }: Props) {
  const [selected, setSelected] = useState<TmdbSuggestion | null>(null)
  const [selectedLocal, setSelectedLocal] = useState<ShowSearchResult | null>(null)
  const [contentType, setContentType] = useState<ContentType>('anime')
  const [folderName, setFolderName] = useState('')
  const [searchQuery, setSearchQuery] = useState(file.parsed_show_name ?? '')
  const [searchMode, setSearchMode] = useState<SearchMode>('suggestions')
  const [tmdbIdQuery, setTmdbIdQuery] = useState('')
  const [tmdbIdMediaType, setTmdbIdMediaType] = useState<'tv' | 'movie'>('tv')

  const { data: config } = useConfig()

  // Title search returns many unrelated results for common-word titles (e.g.
  // "Green Green" surfaces "Green Acres", "Green Lantern", …), so a direct
  // TMDB-ID lookup is offered as a precise alternative.
  const trimmedTmdbIdQuery = tmdbIdQuery.trim()
  const parsedTmdbId = /^\d+$/.test(trimmedTmdbIdQuery) ? parseInt(trimmedTmdbIdQuery, 10) : null

  const {
    candidates,
    isLoading,
    error: candidatesError,
    localCandidates,
    localLoading,
  } = useResolveCandidates({
    mode: searchMode,
    fileId: file.id,
    query: searchQuery,
    tmdbId: parsedTmdbId,
    tmdbMediaType: tmdbIdMediaType,
    parsedName: file.parsed_show_name ?? '',
  })

  const libraryIndex = useLibraryIndex()

  const rematch = useRematchFile()

  // Selecting a result: snap content type (movies -> 'movie', everything else
  // defaults to 'anime'), suggest a folder name, and reset folderEdited so
  // that suggestion isn't immediately treated as a user edit. selected only
  // changes from the one click handler below, so this lives there directly
  // instead of in an effect.
  function selectSuggestion(suggestion: TmdbSuggestion) {
    setSelected(suggestion)
    setSelectedLocal(null)
    setContentType(suggestion.media_type === 'movie' ? 'movie' : 'anime')
    setFolderName(sanitizeFolderName(suggestion.title ?? ''))
  }

  function selectLocal(show: ShowSearchResult) {
    setSelectedLocal(show)
    setSelected(null)
  }

  // The show this file will be assigned to when it already exists locally:
  // either picked directly from the library, or a TMDB pick whose TMDB id is
  // already tracked. In both cases the existing folder is used as-is instead
  // of deriving a new one from the TMDB title.
  const libraryMatch: ExistingShow | null = selected
    ? (libraryIndex.get(`${selected.tmdb_id}:${selected.media_type}`) ?? null)
    : null
  const existing: ExistingShow | null = selectedLocal ?? libraryMatch
  const selectedTitle = selectedLocal?.title ?? selected?.title ?? null
  const selectedYear = year(selectedLocal?.release_date ?? selected?.first_air_date)
  const canConfirm =
    !rematch.isPending &&
    (existing ? Boolean(existing.local_path) : Boolean(selected && folderName.trim() && config))

  function handleConfirm() {
    if (existing) {
      if (!existing.local_path) return
      rematch.mutate({ id: file.id, payload: { show_id: existing.id } }, { onSuccess: onClose })
      return
    }
    if (!selected || !config) return
    const containerPath = folderName.trim()
      ? toContainerPath(contentType, folderName.trim(), config.media_paths)
      : undefined
    rematch.mutate(
      {
        id: file.id,
        payload: {
          tmdb_id: selected.tmdb_id,
          tmdb_media_type: (selected.media_type === 'tv' || selected.media_type === 'movie')
            ? selected.media_type
            : undefined,
          local_path: containerPath,
          content_type: contentType,
        },
      },
      { onSuccess: onClose },
    )
  }

  function handleReset() {
    rematch.mutate({ id: file.id, payload: {} }, { onSuccess: onClose })
  }

  return (
    <Modal
      onClose={onClose}
      tone="dark"
      maxWidth="2xl"
      labelledBy="resolve-file-title"
      className="overflow-hidden flex flex-col max-h-[90vh]"
    >
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between">
          <h2 id="resolve-file-title" className="text-sm font-semibold text-zinc-100">Resolve unmatched file</h2>
          <button onClick={onClose} aria-label="Close dialog" className="text-zinc-400 hover:text-zinc-200 text-lg leading-none">✕</button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
          {/* File info */}
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

          {/* Local library matches */}
          {(localLoading || localCandidates.length > 0) && (
            <div className="space-y-2">
              <div className="text-xs text-zinc-400">In your library</div>
              {localLoading && localCandidates.length === 0 && (
                <div className="text-xs text-zinc-500 py-1">Searching library…</div>
              )}
              <div className="space-y-1.5">
                {localCandidates.map(({ key, local: s }) => s && (
                  <button
                    key={key}
                    onClick={() => selectLocal(s)}
                    className={`w-full flex items-center gap-3 rounded border px-3 py-2 text-left transition-colors ${
                      selectedLocal?.id === s.id
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
                        {s.local_path
                          ? config
                            ? toHostPath(s.local_path, config.media_paths)
                            : s.local_path
                          : 'no local path set'}
                      </div>
                    </div>
                    {s.matched_on !== 'title' && (
                      <span className="text-[10px] uppercase tracking-wide text-zinc-400 shrink-0">
                        matched{' '}
                        {s.matched_on === 'path'
                          ? 'folder'
                          : s.matched_on === 'sys_name'
                            ? 'system name'
                            : 'alias'}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Search */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs text-zinc-400">Search TMDB</label>
              {searchMode === 'suggestions' ? (
                <>
                  <button
                    onClick={() => {
                      setSearchMode('title')
                      setSearchQuery(file.parsed_show_name ?? '')
                    }}
                    className="text-xs text-[var(--color-ocean-400)] hover:text-[var(--color-ocean-300)]"
                  >
                    refine search
                  </button>
                  <button
                    onClick={() => setSearchMode('tmdb_id')}
                    className="text-xs text-[var(--color-ocean-400)] hover:text-[var(--color-ocean-300)]"
                  >
                    search by TMDB ID
                  </button>
                </>
              ) : (
                <button
                  onClick={() => setSearchMode('suggestions')}
                  className="text-xs text-zinc-500 hover:text-zinc-300"
                >
                  back to suggestions
                </button>
              )}
            </div>
            {searchMode === 'title' && (
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search TMDB..."
                className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
              />
            )}
            {searchMode === 'tmdb_id' && (
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  value={tmdbIdQuery}
                  onChange={(e) => setTmdbIdQuery(e.target.value)}
                  placeholder="TMDB ID, e.g. 1668"
                  className="flex-1 bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
                />
                <select
                  value={tmdbIdMediaType}
                  onChange={(e) => setTmdbIdMediaType(e.target.value as 'tv' | 'movie')}
                  className="bg-zinc-800 border border-zinc-600 rounded px-2 py-1.5 text-sm text-zinc-200 focus:outline-none focus:border-[var(--color-ocean-500)]"
                >
                  <option value="tv">TV</option>
                  <option value="movie">Movie</option>
                </select>
              </div>
            )}
          </div>

          {/* TMDB results grid */}
          <CandidateList
            mode={searchMode}
            candidates={candidates}
            isLoading={isLoading}
            error={candidatesError}
            selected={selected}
            onSelect={selectSuggestion}
          />

          {/* Selected show details + path config */}
          {existing && (
            <div className="border border-zinc-700 rounded p-3 space-y-2">
              <div className="text-xs font-medium text-zinc-300">
                Selected: {selectedTitle}
                {selectedYear ? ` (${selectedYear})` : ''}
              </div>
              <div className="text-xs text-emerald-400">
                {selectedLocal
                  ? 'In your library — the file will be assigned to this show.'
                  : `Already in your library as "${existing.title}" — the file will be assigned to it.`}
              </div>
              {existing.local_path ? (
                <div className="space-y-1">
                  <div className="text-xs text-zinc-400">Existing show folder</div>
                  <div className="text-xs text-zinc-300 font-mono break-all">
                    {config ? toHostPath(existing.local_path, config.media_paths) : existing.local_path}
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
          )}

          {selected && !existing && (
            <ResolveConfirm
              selected={selected}
              contentType={contentType}
              folderName={folderName}
              mediaPaths={config?.media_paths}
              onContentTypeChange={setContentType}
              onFolderNameChange={setFolderName}
            />
          )}

          {/* Error */}
          {rematch.isError && (
            <div className="text-xs text-red-400 bg-red-950/30 rounded p-2">
              {rematch.error instanceof Error ? rematch.error.message : 'Match failed'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex items-center justify-between">
          <button
            onClick={handleReset}
            disabled={rematch.isPending}
            className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-50"
          >
            Reset for auto re-match
          </button>
          <div className="flex gap-2">
            <Button onClick={onClose} variant="secondary" tone="dark" size="sm">
              Cancel
            </Button>
            <Button
              onClick={handleConfirm}
              disabled={!canConfirm}
              variant="primary"
              tone="dark"
              size="sm"
            >
              {rematch.isPending ? 'Matching…' : 'Confirm match'}
            </Button>
          </div>
        </div>
    </Modal>
  )
}
