import { useState } from 'react'
import { useConfig } from '@/hooks/useConfig'
import { useRematchFile } from '@/hooks/useFiles'
import { useLibraryIndex } from '@/hooks/useShows'
import { Modal } from '@/components/ui/Modal'
import { CandidateList } from '@/components/resolveFile/CandidateList'
import { ResolveConfirm } from '@/components/resolveFile/ResolveConfirm'
import {
  useResolveCandidates,
  type SearchMode,
} from '@/components/resolveFile/useResolveCandidates'
import { year } from '@/components/resolveFile/year'
import {
  ExistingShowPanel,
  FileInfo,
  LocalMatches,
  MatchError,
  ResolveFooter,
  SearchControls,
  parseTmdbId,
  type ExistingShow,
} from '@/components/resolveFile/ResolveSections'
import { toContainerPath, sanitizeFolderName } from '@/utils/paths'
import type { FileRead, TmdbSuggestion, ContentType, ShowSearchResult } from '@/types/api'

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
  const parsedTmdbId = parseTmdbId(tmdbIdQuery)

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
          <FileInfo file={file} />

          <LocalMatches
            loading={localLoading}
            candidates={localCandidates}
            selectedId={selectedLocal?.id}
            mediaPaths={config?.media_paths}
            onSelect={selectLocal}
          />

          <SearchControls
            mode={searchMode}
            onRefine={() => {
              setSearchMode('title')
              setSearchQuery(file.parsed_show_name ?? '')
            }}
            onSearchById={() => setSearchMode('tmdb_id')}
            onBackToSuggestions={() => setSearchMode('suggestions')}
            query={searchQuery}
            onQueryChange={setSearchQuery}
            tmdbIdQuery={tmdbIdQuery}
            onTmdbIdQueryChange={setTmdbIdQuery}
            tmdbIdMediaType={tmdbIdMediaType}
            onTmdbIdMediaTypeChange={setTmdbIdMediaType}
          />

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
            <ExistingShowPanel
              existing={existing}
              fromLibraryPick={selectedLocal != null}
              title={selectedTitle}
              yearText={selectedYear}
              mediaPaths={config?.media_paths}
            />
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
          {rematch.isError && <MatchError error={rematch.error} />}
        </div>

        <ResolveFooter
          pending={rematch.isPending}
          canConfirm={canConfirm}
          onReset={handleReset}
          onClose={onClose}
          onConfirm={handleConfirm}
        />
    </Modal>
  )
}
