import { useState, useMemo } from 'react'
import { useRematchFile } from '@/hooks/useFiles'
import { useTriggerTask } from '@/hooks/useTasks'
import { useLocalShowSearch, useTmdbSearch, useLibraryIndex } from '@/hooks/useShows'
import { useDebounce } from '@/hooks/useDebounce'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useConfig } from '@/hooks/useConfig'
import {
  FileSummary,
  LibraryResultsPane,
  ModeToggle,
  TmdbGrid,
  TmdbSelectionDetails,
  type RematchMode,
} from '@/components/rematch/RematchPanes'
import { toContainerPath, sanitizeFolderName } from '@/utils/paths'
import type {
  FileRead,
  ShowSearchResult,
  TmdbResult,
  ContentType,
} from '@/types/api'

interface Props {
  file: FileRead
  onClose: () => void
}

export function RematchModal({ file, onClose }: Props) {
  const [mode, setMode] = useState<RematchMode>('tmdb')
  const initialQuery = file.parsed_show_name ?? ''
  const [searchQuery, setSearchQuery] = useState(initialQuery)
  const debouncedQuery = useDebounce(searchQuery, 300)
  const [selectedLibraryShow, setSelectedLibraryShow] = useState<ShowSearchResult | null>(null)
  const [selectedTmdb, setSelectedTmdb] = useState<TmdbResult | null>(null)
  const [contentType, setContentType] = useState<ContentType>('tv')
  const [folderName, setFolderName] = useState('')

  const { data: config } = useConfig()

  const { data: tmdbResults, isFetching: tmdbLoading } = useTmdbSearch(
    mode === 'tmdb' && searchQuery.length >= 2 ? debouncedQuery : '',
    'multi',
  )

  const rematch = useRematchFile()
  const triggerRoute = useTriggerTask()

  // Library search: server-side match on title, alias, sys_name and folder name.
  // Gated on the live input (like the TMDB search) so a mode switch, which clears
  // searchQuery, cannot replay the previous debounced query.
  const { data: libraryResults = [], isFetching: libraryLoading } = useLocalShowSearch(
    mode === 'library' && searchQuery.trim().length >= 2 ? debouncedQuery : '',
    8,
  )
  // Only report "no results" once the debounce and request have both settled.
  const librarySettled = debouncedQuery === searchQuery && !libraryLoading

  const tmdbDisplayResults = useMemo(
    () =>
      (tmdbResults?.results ?? [])
        .filter((r) => r.media_type === 'tv' || r.media_type === 'movie')
        .slice(0, 6),
    [tmdbResults],
  )

  const libraryByTmdbId = useLibraryIndex()

  // When a TMDB result is selected: derive content type from media_type and
  // auto-fill folder. selectedTmdb only changes from the one click handler
  // below, so this lives there directly instead of in an effect.
  function selectTmdb(result: TmdbResult) {
    setSelectedTmdb(result)
    setContentType(result.media_type === 'movie' ? 'movie' : 'tv')
    setFolderName(sanitizeFolderName(result.name ?? result.title ?? ''))
  }

  function switchMode(next: RematchMode) {
    setMode(next)
    setSearchQuery('')
    setSelectedLibraryShow(null)
    setSelectedTmdb(null)
    setFolderName('')
    rematch.reset()
  }

  async function handleConfirm() {
    try {
      if (mode === 'library' && selectedLibraryShow) {
        await rematch.mutateAsync({ id: file.id, payload: { show_id: selectedLibraryShow.id } })
      } else if (mode === 'tmdb' && selectedTmdb) {
        const existing = libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)
        if (existing) {
          await rematch.mutateAsync({ id: file.id, payload: { show_id: existing.id } })
        } else {
          const mediaType =
            selectedTmdb.media_type === 'tv' || selectedTmdb.media_type === 'movie'
              ? selectedTmdb.media_type
              : undefined
          const containerPath = config && folderName.trim()
            ? toContainerPath(contentType, folderName.trim(), config.media_paths)
            : undefined
          await rematch.mutateAsync({
            id: file.id,
            payload: {
              tmdb_id: selectedTmdb.id,
              tmdb_media_type: mediaType ?? null,
              local_path: containerPath,
              content_type: contentType,
            },
          })
        }
      }
      await triggerRoute.mutateAsync({ task_type: 'route' })
      onClose()
    } catch {
      // rematch.error / triggerRoute.error rendered below
    }
  }

  const canConfirm = (() => {
    if (rematch.isPending || triggerRoute.isPending) return false
    if (mode === 'library') {
      return selectedLibraryShow !== null && selectedLibraryShow.local_path != null
    }
    if (!selectedTmdb) return false
    const existing = libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)
    if (existing) return existing.local_path != null
    return !!config && folderName.trim().length > 0
  })()

  const errorMsg = (() => {
    if (rematch.error) {
      return rematch.error instanceof Error ? rematch.error.message : 'Match failed'
    }
    if (triggerRoute.error) {
      return triggerRoute.error instanceof Error
        ? triggerRoute.error.message
        : 'File matched but routing failed — trigger a route task manually'
    }
    return null
  })()

  return (
    <Modal onClose={onClose} tone="dark" maxWidth="2xl" labelledBy="rematch-title" className="flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 id="rematch-title" className="text-sm font-semibold text-zinc-100">Fix show assignment</h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-zinc-400 hover:text-zinc-200 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          <FileSummary file={file} />

          <ModeToggle mode={mode} onChange={switchMode} />

          {/* Search */}
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={mode === 'library' ? 'Search your library…' : 'Search TMDB…'}
            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-[var(--color-ocean-500)]"
            autoFocus
          />

          {/* Library results */}
          {mode === 'library' && (
            <LibraryResultsPane
              results={libraryResults}
              selected={selectedLibraryShow}
              onSelect={setSelectedLibraryShow}
              mediaPaths={config?.media_paths}
              showNoResults={searchQuery.trim().length >= 2 && librarySettled && libraryResults.length === 0}
            />
          )}

          {/* TMDB results */}
          {mode === 'tmdb' && (
            <div className="space-y-3">
              {tmdbLoading && (
                <div className="text-xs text-zinc-500 py-1">Searching…</div>
              )}
              {!tmdbLoading && debouncedQuery.length >= 2 && tmdbDisplayResults.length === 0 && (
                <div className="text-xs text-zinc-500 py-1">No results.</div>
              )}

              {searchQuery.length >= 2 && tmdbDisplayResults.length > 0 && (
                <TmdbGrid results={tmdbDisplayResults} selected={selectedTmdb} onSelect={selectTmdb} />
              )}

              {/* TMDB selection details */}
              {selectedTmdb && (
                <TmdbSelectionDetails
                  existing={libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)}
                  contentType={contentType}
                  onContentTypeChange={setContentType}
                  folderName={folderName}
                  onFolderNameChange={setFolderName}
                  mediaPaths={config?.media_paths}
                />
              )}
            </div>
          )}

          {errorMsg && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {errorMsg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2 shrink-0">
          <Button onClick={onClose} variant="secondary" tone="dark" size="sm">
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={!canConfirm} variant="primary" tone="dark" size="sm">
            {rematch.isPending ? 'Matching…' : 'Match & Route'}
          </Button>
        </div>
    </Modal>
  )
}
