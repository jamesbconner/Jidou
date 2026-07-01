import { useState, useMemo } from 'react'
import { useShowEpisodes } from '@/hooks/useShows'
import { useAssignImportEpisode } from '@/hooks/useShows'
import type { EpisodeList } from '@/types/api'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

function basename(path: string) {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

interface Props {
  showId: number
  episode: EpisodeList
  onClose: () => void
}

export function AssignImportModal({ showId, episode, onClose }: Props) {
  const { data: episodes = [] } = useShowEpisodes(showId)
  const assign = useAssignImportEpisode()
  const [selected, setSelected] = useState('')

  const filePool = useMemo(() => {
    return episodes
      .filter((ep) => ep.tracked_filename && ep.tracked_source === 'import')
      .map((ep) => ({
        filename: ep.tracked_filename!,
        epId: ep.id,
        label: `S${pad2(ep.season_number)}E${pad2(ep.episode_number)} · ${ep.name}`,
      }))
      .sort((a, b) => a.filename.localeCompare(b.filename))
  }, [episodes])

  const currentFilename = episode.tracked_filename

  function handleSave() {
    if (!selected) return
    assign.mutate({ showId, episodeId: episode.id, filename: selected }, { onSuccess: onClose })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-lg rounded-lg bg-zinc-900 shadow-xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 className="text-sm font-semibold text-zinc-100">
            Assign imported file — S{pad2(episode.season_number)}E{pad2(episode.episode_number)} ·{' '}
            {episode.name}
          </h2>
          <button onClick={onClose} aria-label="Close dialog" className="text-zinc-400 hover:text-zinc-200 text-lg leading-none">
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {currentFilename && (
            <div className="bg-zinc-800 rounded p-3 space-y-1">
              <div className="text-xs text-zinc-400">Currently assigned</div>
              <div className="font-mono text-xs text-zinc-200 truncate">{basename(currentFilename)}</div>
            </div>
          )}

          <div className="space-y-1.5">
            <div className="text-xs text-zinc-400">
              Select file from this show's imported pool
            </div>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={assign.isPending}
              className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            >
              <option value="">— pick a file —</option>
              {filePool.map((f) => (
                <option key={f.filename} value={f.filename}>
                  {basename(f.filename)}
                  {f.epId !== episode.id ? ` (currently: ${f.label})` : ' (current)'}
                </option>
              ))}
            </select>
            {filePool.length === 0 && (
              <p className="text-xs text-zinc-500">No imported files found for this show.</p>
            )}
          </div>

          {assign.isError && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {assign.error instanceof Error ? assign.error.message : 'Assignment failed'}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2 shrink-0">
          <button
            onClick={onClose}
            disabled={assign.isPending}
            className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!selected || assign.isPending}
            className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {assign.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
