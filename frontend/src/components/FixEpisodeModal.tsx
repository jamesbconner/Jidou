import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useShowEpisodes, showKeys } from '@/hooks/useShows'
import { fileKeys } from '@/hooks/useFiles'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import { api } from '@/api/client'
import type { FileRead } from '@/types/api'
import { buildSeasonMap } from '@/utils/episodeUtils'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

interface Props {
  file: FileRead
  onClose: () => void
}

export function FixEpisodeModal({ file, onClose }: Props) {
  const [selectedId, setSelectedId] = useState(file.episode_id?.toString() ?? '')
  const qc = useQueryClient()
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)

  const { data: episodes = [] } = useShowEpisodes(file.show_id!)

  const seasonMap = useMemo(() => buildSeasonMap(episodes), [episodes])
  const seasons = useMemo(() => Array.from(seasonMap.keys()).sort((a, b) => a - b), [seasonMap])

  const patch = useMutation({
    mutationFn: (episodeId: number | null) =>
      api.patch<FileRead>(`/files/${file.id}`, {
        episode_id: episodeId,
        ...(episodeId !== null
          ? { status: 'matched', error_message: null }
          : { status: 'unmatched' }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: fileKeys.all })
      qc.invalidateQueries({ queryKey: showKeys.all })
      onClose()
    },
  })

  const currentEp = episodes.find((e) => e.id === file.episode_id)
  const selectedEp = selectedId ? episodes.find((e) => e.id === Number(selectedId)) : undefined
  const isDirty = selectedId !== (file.episode_id?.toString() ?? '')

  function handleSave() {
    patch.mutate(selectedId === '' ? null : Number(selectedId))
  }

  function handleClear() {
    patch.mutate(null)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="fix-episode-title"
    >
      <div ref={dialogRef} className="w-full max-w-lg rounded-lg bg-zinc-900 shadow-xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 id="fix-episode-title" className="text-sm font-semibold text-zinc-100">Fix episode assignment</h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-zinc-400 hover:text-zinc-200 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {/* File info */}
          <div className="bg-zinc-800 rounded p-3 space-y-1">
            <div className="text-xs text-zinc-400">File</div>
            <div className="font-mono text-xs text-zinc-200 truncate">{file.original_filename}</div>
            <div className="text-xs text-zinc-500 mt-0.5">
              Show: {file.show?.title ?? `#${file.show_id}`}
            </div>
          </div>

          {/* Current assignment */}
          {currentEp ? (
            <div className="text-xs text-zinc-400">
              Currently:{' '}
              <span className="text-zinc-200">
                S{pad2(currentEp.season_number)}E{pad2(currentEp.episode_number)} ·{' '}
                {currentEp.name}
              </span>
            </div>
          ) : (
            <div className="text-xs text-zinc-500">No episode currently assigned.</div>
          )}

          {/* Re-routing warning for already-routed files */}
          {file.status === 'routed' && (
            <div className="text-xs text-amber-400 bg-amber-950/30 border border-amber-800/40 rounded p-2">
              This file has already been routed to disk. Changing the episode will reset it to
              matched so it gets re-routed to the correct location.
            </div>
          )}

          {/* Episode picker */}
          <div className="space-y-1.5">
            <div className="text-xs text-zinc-400">Select episode</div>
            <select
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
              disabled={patch.isPending}
              className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            >
              <option value="">— none —</option>
              {seasons.map((sn) => (
                <optgroup key={sn} label={`Season ${sn}`}>
                  {(seasonMap.get(sn) ?? [])
                    .sort((a, b) => a.episode_number - b.episode_number)
                    .map((ep) => (
                      <option key={ep.id} value={ep.id}>
                        {`S${pad2(ep.season_number)}E${pad2(ep.episode_number)} — ${ep.name}`}
                        {ep.file_tracked && ep.id !== file.episode_id ? ' (taken)' : ''}
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </div>

          {/* Show what will change */}
          {isDirty && selectedEp && selectedEp.id !== file.episode_id && (
            <div className="text-xs text-zinc-400">
              New assignment:{' '}
              <span className="text-zinc-200">
                S{pad2(selectedEp.season_number)}E{pad2(selectedEp.episode_number)} ·{' '}
                {selectedEp.name}
              </span>
            </div>
          )}

          {/* Error */}
          {patch.isError && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {patch.error instanceof Error ? patch.error.message : 'Failed to update episode'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex items-center justify-between shrink-0">
          <button
            onClick={handleClear}
            disabled={patch.isPending || file.episode_id == null}
            className="text-xs text-zinc-400 hover:text-red-400 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Clear assignment
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              disabled={patch.isPending}
              className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!isDirty || patch.isPending}
              className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {patch.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
