import { useState, useMemo } from 'react'
import { useShowEpisodes } from '@/hooks/useShows'
import { useResolveOrphan, useDismissOrphan } from '@/hooks/useOrphans'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import type { OrphanedTrackingRecord, EpisodeList } from '@/types/api'

interface Props {
  orphan: OrphanedTrackingRecord
  onClose: () => void
}

function basename(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

export function OrphanResolveModal({ orphan, onClose }: Props) {
  const [search, setSearch] = useState('')
  const [selectedEpisode, setSelectedEpisode] = useState<EpisodeList | null>(null)

  const { data: episodes = [], isLoading } = useShowEpisodes(orphan.show_id)
  const resolve = useResolveOrphan()
  const dismiss = useDismissOrphan()

  const filtered = useMemo(() => {
    if (!search.trim()) return episodes
    const q = search.toLowerCase()
    return episodes.filter(
      (ep) =>
        ep.name.toLowerCase().includes(q) ||
        `s${String(ep.season_number).padStart(2, '0')}e${String(ep.episode_number).padStart(2, '0')}`.includes(q),
    )
  }, [episodes, search])

  async function handleResolve() {
    if (!selectedEpisode) return
    try {
      await resolve.mutateAsync({ orphanId: orphan.id, episodeId: selectedEpisode.id })
      onClose()
    } catch {
      // error rendered below
    }
  }

  async function handleDismiss() {
    try {
      await dismiss.mutateAsync(orphan.id)
      onClose()
    } catch {
      // error rendered below
    }
  }

  const filename = orphan.tracked_filename_display
    ? basename(orphan.tracked_filename_display)
    : null
  const seLabel = `S${String(orphan.old_season_number).padStart(2, '0')}E${String(orphan.old_episode_number).padStart(2, '0')}`
  const errorMsg =
    resolve.error instanceof Error
      ? resolve.error.message
      : resolve.error
        ? 'Resolve failed'
        : dismiss.error instanceof Error
          ? dismiss.error.message
          : dismiss.error
            ? 'Dismiss failed'
            : null

  return (
    <Modal onClose={onClose} tone="dark" maxWidth="xl" labelledBy="orphan-resolve-title" className="flex flex-col max-h-[85vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 id="orphan-resolve-title" className="text-sm font-semibold text-zinc-100">Manual Episode Match</h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-zinc-400 hover:text-zinc-200 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-4">
          {/* Orphan details */}
          <div className="bg-zinc-800 rounded p-3 space-y-1.5 text-xs">
            <div>
              <span className="text-zinc-400">Show: </span>
              <span className="text-zinc-200 font-medium">{orphan.show_title}</span>
            </div>
            {filename && (
              <div>
                <span className="text-zinc-400">File: </span>
                <span className="text-zinc-200 font-mono">{filename}</span>
              </div>
            )}
            <div>
              <span className="text-zinc-400">Old position: </span>
              <span className="text-zinc-200">{seLabel}</span>
            </div>
            <div>
              <span className="text-zinc-400">Source: </span>
              <span className={`font-medium ${orphan.tracked_source === 'import' ? 'text-blue-400' : 'text-green-400'}`}>
                {orphan.tracked_source === 'import' ? 'Path import' : 'Downloaded'}
              </span>
            </div>
          </div>

          {/* Episode search */}
          <div className="space-y-2">
            <p className="text-xs text-zinc-400">
              Select the correct episode for this file. Search by name or S##E## code.
            </p>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter episodes…"
              className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
              autoFocus
            />
          </div>

          {/* Episode list */}
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {isLoading && <p className="text-xs text-zinc-500">Loading episodes…</p>}
            {!isLoading && filtered.length === 0 && (
              <p className="text-xs text-zinc-500">No episodes match.</p>
            )}
            {filtered.map((ep) => {
              const code = `S${String(ep.season_number).padStart(2, '0')}E${String(ep.episode_number).padStart(2, '0')}`
              const selected = selectedEpisode?.id === ep.id
              return (
                <button
                  key={ep.id}
                  onClick={() => setSelectedEpisode(ep)}
                  className={`w-full text-left px-3 py-2 rounded border text-xs transition-colors ${
                    selected
                      ? 'border-indigo-500 bg-indigo-950/50'
                      : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
                  }`}
                >
                  <span className="font-mono text-zinc-400 mr-2">{code}</span>
                  <span className="text-zinc-200">{ep.name}</span>
                  {ep.air_date && (
                    <span className="text-zinc-500 ml-2">{ep.air_date}</span>
                  )}
                  {ep.file_tracked && (
                    <span className="ml-2 text-amber-400 text-[10px]">already tracked</span>
                  )}
                </button>
              )
            })}
          </div>

          {errorMsg && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {errorMsg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex justify-between items-center shrink-0">
          <Button onClick={handleDismiss} disabled={dismiss.isPending} variant="danger" tone="dark" size="sm">
            {dismiss.isPending ? 'Dismissing…' : 'Dismiss record'}
          </Button>
          <div className="flex gap-2">
            <Button onClick={onClose} variant="secondary" tone="dark" size="sm">
              Cancel
            </Button>
            <Button onClick={handleResolve} disabled={!selectedEpisode || resolve.isPending} variant="primary" tone="dark" size="sm">
              {resolve.isPending ? 'Saving…' : 'Confirm Match'}
            </Button>
          </div>
        </div>
    </Modal>
  )
}
