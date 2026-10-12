import { useEffect, useMemo, useState } from 'react'
import { useFilesByShow, useLinkEpisodeFile, useLinkExistingFile, useVerifyPaths } from '@/hooks/useFiles'
import { useShowEpisodes, useAssignImportEpisode } from '@/hooks/useShows'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useConfig } from '@/hooks/useConfig'
import {
  ExistingFilePane,
  EXISTING_PREFIX,
  IMPORTED_PREFIX,
  ModeSwitch,
  PathPane,
  type LinkMode,
} from '@/components/linkFile/LinkFilePanes'
import { parseContainerPath } from '@/utils/paths'
import type { ContentType, EpisodeList, FileRead, FileStatus } from '@/types/api'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

interface Props {
  showId: number
  showLocalPath: string | null
  episode: EpisodeList
  onClose: () => void
}

// Files mid-transfer or otherwise not real, matchable content — excluded
// from the reassignment pool regardless of which episode (if any) they
// currently track.
const UNAVAILABLE_STATUSES = new Set<FileStatus>([
  'discovered',
  'downloading',
  'pending',
  'routing',
  'ignored',
  'seeded',
  'missing',
])

export function LinkFileModal({ showId, showLocalPath, episode, onClose }: Props) {
  const [mode, setMode] = useState<LinkMode>('existing')
  const [selected, setSelected] = useState('')
  const [contentType, setContentType] = useState<ContentType>('tv')
  const [relativePath, setRelativePath] = useState('')

  const { data: showFiles = [], isLoading: filesLoading } = useFilesByShow(showId)
  const { data: episodes = [] } = useShowEpisodes(showId)

  // Any real file for the show that isn't currently backing an episode —
  // covers files displaced by a mis-route (which keep their prior status,
  // e.g. 'routed', rather than resetting to 'unmatched') alongside files
  // that never matched in the first place.
  const candidateFiles = useMemo(
    () =>
      showFiles
        .filter((f) => f.episode_id === null && !UNAVAILABLE_STATUSES.has(f.status))
        .sort((a, b) => a.original_filename.localeCompare(b.original_filename)),
    [showFiles],
  )

  // Filenames tracked via path-import have no DownloadedFile row, so they
  // can't come from useFilesByShow — pulled separately from the show's
  // other episodes, same pool AssignImportModal draws from. Never existence-
  // checked: an import-tracked path may be a host/catalog reference (bulk
  // path-import can record e.g. a Windows drive-letter path) rather than
  // something visible inside this container's filesystem, so a "missing"
  // result here wouldn't be trustworthy — see file_reconciliation.py.
  const importPool = useMemo(() => {
    return episodes
      .filter((ep) => ep.tracked_filename && ep.tracked_source === 'import')
      .map((ep) => ({
        filename: ep.tracked_filename!,
        displayName: ep.tracked_filename_display ?? ep.tracked_filename!,
        label: `S${pad2(ep.season_number)}E${pad2(ep.episode_number)} · ${ep.name}`,
      }))
      .sort((a, b) => a.filename.localeCompare(b.filename))
  }, [episodes])

  // Same host/catalog-path caveat applies to any DownloadedFile row created
  // by that same import path (remote_path carries the synthetic-import://
  // marker) — exclude those from the live check too, same reasoning as
  // importPool above.
  const isImportBacked = (f: FileRead) => f.remote_path.startsWith('synthetic-import://')

  // Live existence check on top of the DB-derived candidates above: a file
  // renamed/moved/deleted outside the app still has a stale DB row until a
  // Scan Local Files pass reconciles it — this keeps the picker honest in
  // the meantime, for the subset of candidates it's safe to check.
  const verifyPaths = useMemo(
    () => candidateFiles.flatMap((f) => (f.local_path && !isImportBacked(f) ? [f.local_path] : [])),
    [candidateFiles],
  )
  const { data: verified, isLoading: verifyLoading } = useVerifyPaths(verifyPaths)
  const existingPaths = verified?.existing

  const availableFiles = useMemo(
    () =>
      candidateFiles.filter(
        (f) =>
          isImportBacked(f) ||
          !f.local_path ||
          existingPaths === undefined ||
          existingPaths.includes(f.local_path),
      ),
    [candidateFiles, existingPaths],
  )

  const { data: config } = useConfig()
  const mediaPaths = config?.media_paths

  // Seed content type + a starting folder name from the show's existing local
  // path (the same base it already lives under) once config loads — but only
  // the first time, so it doesn't clobber what the user has already typed.
  useEffect(() => {
    if (!mediaPaths || relativePath !== '') return
    const parsed = parseContainerPath(showLocalPath, mediaPaths)
    // Seeding editable state from data that only becomes available
    // asynchronously (mediaPaths loads after mount) — not a same-render
    // derivation, so this can't move to a render-time computation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setContentType(parsed.contentType)
    setRelativePath(parsed.folderName ? `${parsed.folderName}/` : '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaPaths])

  const containerBase = mediaPaths?.[contentType].container
  const relativeTrimmed = relativePath.replace(/^\/+/, '').trim()
  const fullPath = containerBase && relativeTrimmed ? `${containerBase}/${relativeTrimmed}` : null

  const linkExisting = useLinkExistingFile(episode.id, { onSuccess: onClose })

  const linkPath = useLinkEpisodeFile()
  const assignImport = useAssignImportEpisode()

  function handleSave() {
    if (mode === 'existing') {
      if (selected.startsWith(EXISTING_PREFIX)) {
        linkExisting.mutate(Number(selected.slice(EXISTING_PREFIX.length)))
      } else if (selected.startsWith(IMPORTED_PREFIX)) {
        assignImport.mutate(
          { showId, episodeId: episode.id, filename: selected.slice(IMPORTED_PREFIX.length) },
          { onSuccess: onClose },
        )
      }
    } else {
      if (!fullPath) return
      linkPath.mutate(
        { showId, episodeId: episode.id, path: fullPath },
        { onSuccess: onClose },
      )
    }
  }

  const pending = linkExisting.isPending || linkPath.isPending || assignImport.isPending
  const error = linkExisting.error ?? linkPath.error ?? assignImport.error
  const canSave = mode === 'existing' ? !!selected : !!fullPath

  return (
    <Modal onClose={onClose} tone="dark" labelledBy="link-file-title" className="flex flex-col max-h-[90vh]">
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 id="link-file-title" className="text-sm font-semibold text-zinc-100">
            Match file — S{pad2(episode.season_number)}E{pad2(episode.episode_number)} ·{' '}
            {episode.name}
          </h2>
          <button onClick={onClose} aria-label="Close dialog" className="text-zinc-400 hover:text-zinc-200 text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          <ModeSwitch mode={mode} onChange={setMode} />

          {mode === 'existing' ? (
            <ExistingFilePane
              selected={selected}
              onSelect={setSelected}
              disabled={pending || filesLoading || verifyLoading}
              loading={filesLoading || verifyLoading}
              availableFiles={availableFiles}
              importPool={importPool}
            />
          ) : (
            <PathPane
              contentType={contentType}
              onContentTypeChange={setContentType}
              relativePath={relativePath}
              onRelativePathChange={setRelativePath}
              fullPath={fullPath}
              disabled={pending}
            />
          )}

          {error && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {error instanceof Error ? error.message : 'Failed to link file'}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2 shrink-0">
          <Button onClick={onClose} disabled={pending} variant="secondary" tone="dark" size="sm">
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!canSave || pending} variant="primary" tone="dark" size="sm">
            {pending ? 'Saving…' : 'Save'}
          </Button>
        </div>
    </Modal>
  )
}
