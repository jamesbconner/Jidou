import { useEffect, useMemo, useState } from 'react'
import { useShowEpisodes } from '@/hooks/useShows'
import { useLinkEpisodeFile } from '@/hooks/useFiles'
import { useScanShowLocalFiles } from '@/hooks/useShows'
import { useFocusTrap } from '@/hooks/useFocusTrap'
import { buildSeasonMap } from '@/utils/episodeUtils'
import type { ScannedFileMatch } from '@/types/api'

function pad2(n: number) {
  return String(n).padStart(2, '0')
}

function basename(path: string) {
  return path.replace(/\\/g, '/').split('/').pop() ?? path
}

interface Props {
  showId: number
  onClose: () => void
}

type RowOutcome = { kind: 'linked' } | { kind: 'failed'; message: string }

export function ScanLocalFilesModal({ showId, onClose }: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)
  const scan = useScanShowLocalFiles()
  const linkFile = useLinkEpisodeFile()
  const { data: episodes = [] } = useShowEpisodes(showId)

  const [selections, setSelections] = useState<Record<string, string>>({})
  // Paths the user has explicitly changed via the <select> — distinct from
  // `selections` itself, so the reseed effect below can tell "user chose
  // this" apart from "auto-seeded from a since-superseded scan" and only
  // preserve the former across a Rescan.
  const [touchedPaths, setTouchedPaths] = useState<Set<string>>(new Set())
  const [pendingPaths, setPendingPaths] = useState<Set<string>>(new Set())
  const [outcomes, setOutcomes] = useState<Record<string, RowOutcome>>({})
  const [bulkPending, setBulkPending] = useState(false)

  useEffect(() => {
    scan.mutate(showId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showId])

  // Seed each row's picker with its proposed episode on every fresh scan
  // result — except for paths the user has manually touched, which keep
  // their own choice across a Rescan instead of being overwritten.
  useEffect(() => {
    if (!scan.data) return
    setSelections((prev) => {
      const next = { ...prev }
      for (const row of scan.data!) {
        if (!touchedPaths.has(row.path)) {
          next[row.path] = row.status === 'matched' && row.episode ? String(row.episode.id) : ''
        }
      }
      return next
    })
  }, [scan.data, touchedPaths])

  const seasonMap = useMemo(() => buildSeasonMap(episodes), [episodes])
  const seasons = useMemo(() => Array.from(seasonMap.keys()).sort((a, b) => a - b), [seasonMap])
  const episodeById = useMemo(() => new Map(episodes.map((e) => [e.id, e])), [episodes])

  function handleSelectChange(path: string, value: string) {
    setTouchedPaths((prev) => new Set(prev).add(path))
    setSelections((prev) => ({ ...prev, [path]: value }))
  }

  function rowIsActionable(row: ScannedFileMatch): boolean {
    const selected = selections[row.path]
    if (!selected) return false
    const ep = episodeById.get(Number(selected))
    return ep != null && !ep.file_tracked
  }

  async function linkRow(row: ScannedFileMatch) {
    const selected = selections[row.path]
    if (!selected) return
    setPendingPaths((prev) => new Set(prev).add(row.path))
    try {
      await linkFile.mutateAsync({ showId, episodeId: Number(selected), path: row.path })
      setOutcomes((prev) => ({ ...prev, [row.path]: { kind: 'linked' } }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to link'
      setOutcomes((prev) => ({ ...prev, [row.path]: { kind: 'failed', message } }))
    } finally {
      setPendingPaths((prev) => {
        const next = new Set(prev)
        next.delete(row.path)
        return next
      })
    }
  }

  async function handleConfirmAll() {
    const rows = (scan.data ?? []).filter(
      (row) => outcomes[row.path]?.kind !== 'linked' && rowIsActionable(row),
    )
    setBulkPending(true)
    try {
      // Sequential, not concurrent: two rows could target the same episode
      // (manually assigned, or a scan-time collision the backend didn't
      // catch), and firing every link-file call at once would race past the
      // backend's already-tracked check before either commit lands. The
      // backend also takes a row lock (link_episode_file's with_for_update)
      // as defense in depth, but avoiding the race client-side means the
      // user sees an honest per-row result instead of a surprise 422.
      for (const row of rows) {
        await linkRow(row)
      }
    } finally {
      setBulkPending(false)
    }
  }

  const rows = scan.data ?? []
  const actionableCount = rows.filter(
    (row) => outcomes[row.path]?.kind !== 'linked' && rowIsActionable(row),
  ).length

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="scan-local-files-title"
    >
      <div
        ref={dialogRef}
        className="w-full max-w-3xl rounded-lg bg-zinc-900 shadow-xl flex flex-col max-h-[90vh]"
      >
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 id="scan-local-files-title" className="text-sm font-semibold text-zinc-100">
            Scan local files
          </h2>
          <button
            onClick={onClose}
            aria-label="Close dialog"
            className="text-zinc-400 hover:text-zinc-200 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-3">
          {scan.isPending && <p className="text-sm text-zinc-400">Scanning…</p>}
          {scan.isError && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {scan.error instanceof Error ? scan.error.message : 'Scan failed'}
            </div>
          )}
          {scan.isSuccess && rows.length === 0 && (
            <p className="text-sm text-zinc-500">
              No new media files found under this show&apos;s local path.
            </p>
          )}

          {rows.map((row) => {
            const outcome = outcomes[row.path]
            const isPending = pendingPaths.has(row.path)
            const selected = selections[row.path] ?? ''
            const selectedEp = selected ? episodeById.get(Number(selected)) : undefined
            const actionable = rowIsActionable(row) && outcome?.kind !== 'linked'

            return (
              <div
                key={row.path}
                className="bg-zinc-800 rounded p-3 space-y-2 border border-zinc-700"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-mono text-xs text-zinc-200 truncate">
                      {basename(row.path)}
                    </p>
                    <p className="text-[11px] text-zinc-500">
                      {row.season != null ? `S${pad2(row.season)}` : 'S?'}
                      {row.episode_number != null ? `E${pad2(row.episode_number)}` : 'E?'}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 text-[11px] px-1.5 py-0.5 rounded font-medium ${
                      outcome?.kind === 'linked'
                        ? 'bg-green-900/40 text-green-400'
                        : row.status === 'matched'
                          ? 'bg-indigo-900/40 text-indigo-400'
                          : row.status === 'conflict'
                            ? 'bg-amber-900/40 text-amber-400'
                            : 'bg-zinc-700 text-zinc-400'
                    }`}
                  >
                    {outcome?.kind === 'linked'
                      ? 'linked'
                      : outcome?.kind === 'failed'
                        ? 'failed'
                        : row.status}
                  </span>
                </div>

                {outcome?.kind !== 'linked' && (
                  <div className="flex items-center gap-2">
                    <select
                      value={selected}
                      onChange={(e) => handleSelectChange(row.path, e.target.value)}
                      disabled={isPending}
                      className="flex-1 bg-zinc-900 border border-zinc-600 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500 disabled:opacity-50"
                    >
                      <option value="">— select episode —</option>
                      {seasons.map((sn) => (
                        <optgroup key={sn} label={`Season ${sn}`}>
                          {(seasonMap.get(sn) ?? [])
                            .sort((a, b) => a.episode_number - b.episode_number)
                            .map((ep) => (
                              <option key={ep.id} value={ep.id}>
                                {`S${pad2(ep.season_number)}E${pad2(ep.episode_number)} — ${ep.name}`}
                                {ep.file_tracked ? ' (taken)' : ''}
                              </option>
                            ))}
                        </optgroup>
                      ))}
                    </select>
                    <button
                      onClick={() => linkRow(row)}
                      disabled={!actionable || isPending}
                      className="shrink-0 px-2.5 py-1 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      {isPending ? 'Linking…' : 'Link'}
                    </button>
                  </div>
                )}
                {selectedEp && selectedEp.file_tracked && outcome?.kind !== 'linked' && (
                  <p className="text-[11px] text-amber-500">
                    This episode is already tracked — pick a different one to link this file.
                  </p>
                )}
                {outcome?.kind === 'failed' && (
                  <p className="text-[11px] text-red-400">{outcome.message}</p>
                )}
              </div>
            )
          })}
        </div>

        <div className="px-5 py-3 border-t border-zinc-700 flex items-center justify-between shrink-0">
          <button
            onClick={() => scan.mutate(showId)}
            disabled={scan.isPending || bulkPending}
            className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-40"
          >
            Rescan
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              Close
            </button>
            <button
              onClick={handleConfirmAll}
              disabled={actionableCount === 0 || bulkPending}
              className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {bulkPending ? 'Linking…' : `Confirm All Matched (${actionableCount})`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
