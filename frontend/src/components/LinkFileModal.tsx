import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useUnmatchedFilesForShow, useLinkEpisodeFile, fileKeys } from '@/hooks/useFiles'
import { showKeys } from '@/hooks/useShows'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import { api } from '@/api/client'
import { parseContainerPath } from '@/utils/paths'
import type { AppConfig, ContentType, EpisodeList, FileRead } from '@/types/api'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

function basename(path: string) {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

interface Props {
  showId: number
  showLocalPath: string | null
  episode: EpisodeList
  onClose: () => void
}

export function LinkFileModal({ showId, showLocalPath, episode, onClose }: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)
  const qc = useQueryClient()
  const [mode, setMode] = useState<'existing' | 'path'>('existing')
  const [selectedFileId, setSelectedFileId] = useState('')
  const [contentType, setContentType] = useState<ContentType>('tv')
  const [relativePath, setRelativePath] = useState('')

  const { data: unmatchedFiles = [], isLoading: filesLoading } = useUnmatchedFilesForShow(showId)

  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })
  const mediaPaths = config?.media_paths

  // Seed content type + a starting folder name from the show's existing local
  // path (the same base it already lives under) once config loads — but only
  // the first time, so it doesn't clobber what the user has already typed.
  useEffect(() => {
    if (!mediaPaths || relativePath !== '') return
    const parsed = parseContainerPath(showLocalPath, mediaPaths)
    setContentType(parsed.contentType)
    setRelativePath(parsed.folderName ? `${parsed.folderName}/` : '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaPaths])

  const containerBase = mediaPaths?.[contentType].container
  const relativeTrimmed = relativePath.replace(/^\/+/, '').trim()
  const fullPath = containerBase && relativeTrimmed ? `${containerBase}/${relativeTrimmed}` : null

  const linkExisting = useMutation({
    mutationFn: (fileId: number) =>
      api.patch<FileRead>(`/files/${fileId}`, {
        episode_id: episode.id,
        status: 'matched',
        error_message: null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: fileKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
      onClose()
    },
  })

  const linkPath = useLinkEpisodeFile()

  function handleSave() {
    if (mode === 'existing') {
      if (!selectedFileId) return
      linkExisting.mutate(Number(selectedFileId))
    } else {
      if (!fullPath) return
      linkPath.mutate(
        { showId, episodeId: episode.id, path: fullPath },
        { onSuccess: onClose },
      )
    }
  }

  const pending = linkExisting.isPending || linkPath.isPending
  const error = linkExisting.error ?? linkPath.error
  const canSave = mode === 'existing' ? !!selectedFileId : !!fullPath

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="link-file-title"
    >
      <div ref={dialogRef} className="w-full max-w-lg rounded-lg bg-zinc-900 shadow-xl flex flex-col max-h-[90vh]">
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
          <div className="flex gap-1.5 text-xs">
            <button
              onClick={() => setMode('existing')}
              className={`px-3 py-1.5 rounded border ${
                mode === 'existing'
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : 'border-zinc-600 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              Pick unmatched file
            </button>
            <button
              onClick={() => setMode('path')}
              className={`px-3 py-1.5 rounded border ${
                mode === 'path'
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : 'border-zinc-600 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              Enter file path
            </button>
          </div>

          {mode === 'existing' ? (
            <div className="space-y-1.5">
              <div className="text-xs text-zinc-400">
                Select an unmatched file already tracked for this show
              </div>
              <select
                value={selectedFileId}
                onChange={(e) => setSelectedFileId(e.target.value)}
                disabled={pending || filesLoading}
                className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
              >
                <option value="">— pick a file —</option>
                {unmatchedFiles.map((f) => (
                  <option key={f.id} value={f.id}>
                    {basename(f.original_filename)}
                  </option>
                ))}
              </select>
              {!filesLoading && unmatchedFiles.length === 0 && (
                <p className="text-xs text-zinc-500">No unmatched files found for this show.</p>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="space-y-1">
                <div className="text-xs text-zinc-400">Content type</div>
                <div className="flex gap-4">
                  {(['anime', 'tv', 'movie'] as ContentType[]).map((t) => (
                    <label key={t} className="flex items-center gap-1.5 text-sm text-zinc-200 cursor-pointer">
                      <input
                        type="radio"
                        name="link_file_content_type"
                        value={t}
                        checked={contentType === t}
                        onChange={() => setContentType(t)}
                        disabled={pending}
                        className="accent-indigo-600"
                      />
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="text-xs text-zinc-400">
                  Path within the {contentType} folder (show / season / filename)
                </div>
                <input
                  value={relativePath}
                  onChange={(e) => setRelativePath(e.target.value)}
                  disabled={pending}
                  placeholder="Show Name/Season 01/show.s01e01.mkv"
                  className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 font-mono focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                  autoFocus
                />
                {fullPath && (
                  <p className="text-xs text-zinc-500 font-mono truncate">{fullPath}</p>
                )}
              </div>
            </div>
          )}

          {error && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {error instanceof Error ? error.message : 'Failed to link file'}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2 shrink-0">
          <button
            onClick={onClose}
            disabled={pending}
            className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave || pending}
            className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {pending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
