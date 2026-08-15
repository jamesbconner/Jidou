import { useEffect, useRef, useState } from 'react'
import { useScanShowLocalMovieFile } from '@/hooks/useShows'
import { useLinkMovieFile } from '@/hooks/useFiles'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import type { ScannedFileMatch } from '@/types/api'

interface Props {
  showId: number
  onClose: () => void
  /**
   * True when opened from the movie's existing linked file ("Fix Match")
   * rather than the empty-state "Scan Local Files" button. Passed through
   * to the scan/link calls so the backend treats this movie's current link
   * as replaceable instead of a blocking conflict, and adjusts copy
   * accordingly.
   */
  replace?: boolean
}

type RowOutcome = { kind: 'linked' } | { kind: 'failed'; message: string }

// The one character a browser text input could produce that scan_show_directory's
// encode_path_bytes (see path_transport.py) would otherwise misinterpret as the
// start of a percent-encoded byte escape -- scanned rows already arrive
// pre-encoded from the backend, but a manually typed path never went through
// that encoding.
function encodePathForApi(raw: string): string {
  return raw.replace(/%/g, '%25')
}

export function ScanLocalMovieFileModal({ showId, onClose, replace = false }: Props) {
  const scan = useScanShowLocalMovieFile()
  const linkFile = useLinkMovieFile()

  const [manualPath, setManualPath] = useState('')
  const [pendingPaths, setPendingPaths] = useState<Set<string>>(new Set())
  const [outcomes, setOutcomes] = useState<Record<string, RowOutcome>>({})
  // Mirrors pendingPaths but updated synchronously — setState is batched, so
  // a fast click on another row can invoke linkRow again before the
  // re-render that would disable its button lands. Checking this ref first
  // closes that window without waiting on React. A movie can only ever have
  // one linked file, so this blocks ANY concurrent link request, not just a
  // second click on the same row -- two simultaneous requests for different
  // rows would otherwise both pass the backend's "not already linked" check
  // before either commits.
  const inFlightRef = useRef(false)

  useEffect(() => {
    scan.mutate({ showId, replace })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showId, replace])

  async function performLink(path: string) {
    if (inFlightRef.current) return
    inFlightRef.current = true
    setPendingPaths((prev) => new Set(prev).add(path))
    try {
      await linkFile.mutateAsync({ showId, path, replace })
      setOutcomes((prev) => ({ ...prev, [path]: { kind: 'linked' } }))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to link'
      setOutcomes((prev) => ({ ...prev, [path]: { kind: 'failed', message } }))
    } finally {
      inFlightRef.current = false
      setPendingPaths((prev) => {
        const next = new Set(prev)
        next.delete(path)
        return next
      })
    }
  }

  function linkRow(row: ScannedFileMatch) {
    return performLink(row.path)
  }

  const manualKey = encodePathForApi(manualPath.trim())
  function linkManualPath() {
    if (!manualPath.trim()) return
    return performLink(manualKey)
  }

  const rows = scan.data ?? []
  // A movie can only ever have one linked file. Every untracked row in a
  // shared-root scan comes back 'matched' (see scan-local-movie-file), since
  // several other untracked titles routinely sit in the same directory — but
  // once any one of them links (or is in the middle of linking), every
  // other row must stop being actionable immediately: hasLinkedAny alone
  // only covers the already-succeeded case, so pendingPaths.size > 0 is
  // checked too, closing the window while a request is still in flight
  // (inFlightRef above blocks the synchronous double-click case within
  // that same window).
  const hasLinkedAny = Object.values(outcomes).some((o) => o.kind === 'linked')
  const anyPending = pendingPaths.size > 0

  return (
    <Modal
      onClose={onClose}
      tone="dark"
      maxWidth="2xl"
      labelledBy="scan-local-movie-file-title"
      className="flex flex-col max-h-[90vh]"
    >
      <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
        <h2 id="scan-local-movie-file-title" className="text-sm font-semibold text-zinc-100">
          {replace ? 'Fix movie file' : 'Scan local files'}
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
        <div className="space-y-1.5">
          <label
            htmlFor="movie-file-manual-path"
            className="text-xs text-zinc-400 block"
          >
            Enter the file path directly
          </label>
          <div className="flex gap-2">
            <input
              id="movie-file-manual-path"
              type="text"
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              placeholder="/data/media/movies/Movie Title (2024).mkv"
              className="flex-1 min-w-0 bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={linkManualPath}
              disabled={!manualPath.trim() || anyPending || hasLinkedAny}
              className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            >
              {pendingPaths.has(manualKey) ? 'Linking…' : 'Link path'}
            </button>
          </div>
          {outcomes[manualKey]?.kind === 'failed' && (
            <p className="text-[11px] text-red-400">{outcomes[manualKey].message}</p>
          )}
          {outcomes[manualKey]?.kind === 'linked' && (
            <p className="text-[11px] text-green-400">Linked.</p>
          )}
        </div>

        <p className="text-xs text-zinc-500">Or pick a file found under this movie&apos;s local path:</p>

        {scan.isPending && <p className="text-sm text-zinc-400">Scanning…</p>}
        {scan.isError && (
          <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
            {scan.error instanceof Error ? scan.error.message : 'Scan failed'}
          </div>
        )}
        {scan.isSuccess && rows.length === 0 && (
          <p className="text-sm text-zinc-500">
            {replace ? 'No other' : 'No new'} media files found under this movie&apos;s local
            path.
          </p>
        )}

        {rows.map((row) => {
          const outcome = outcomes[row.path]
          const isPending = pendingPaths.has(row.path)
          const actionable =
            row.status === 'matched' &&
            outcome?.kind !== 'linked' &&
            !hasLinkedAny &&
            !anyPending

          return (
            <div
              key={row.path}
              className="bg-zinc-800 rounded p-3 flex items-center justify-between gap-3 border border-zinc-700"
            >
              <div className="min-w-0">
                <p className="font-mono text-xs text-zinc-200 truncate">{row.filename}</p>
                {outcome?.kind === 'failed' && (
                  <p className="text-[11px] text-red-400 mt-0.5">{outcome.message}</p>
                )}
                {(row.status === 'conflict' || (hasLinkedAny && outcome?.kind !== 'linked')) && (
                  <p className="text-[11px] text-amber-500 mt-0.5">
                    This movie already has a linked file.
                  </p>
                )}
              </div>
              <div className="shrink-0 flex items-center gap-2">
                <span
                  className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${
                    outcome?.kind === 'linked'
                      ? 'bg-green-900/40 text-green-400'
                      : actionable
                        ? 'bg-indigo-900/40 text-indigo-400'
                        : 'bg-amber-900/40 text-amber-400'
                  }`}
                >
                  {outcome?.kind === 'linked'
                    ? 'linked'
                    : outcome?.kind === 'failed'
                      ? 'failed'
                      : actionable
                        ? row.status
                        : 'conflict'}
                </span>
                {outcome?.kind !== 'linked' && (
                  <button
                    onClick={() => linkRow(row)}
                    disabled={!actionable || isPending}
                    className="px-2.5 py-1 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    {isPending ? 'Linking…' : 'Link'}
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="px-5 py-3 border-t border-zinc-700 flex items-center justify-between shrink-0">
        <button
          onClick={() => scan.mutate({ showId, replace })}
          disabled={scan.isPending}
          className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-40"
        >
          Rescan
        </button>
        <Button onClick={onClose} variant="secondary" tone="dark" size="sm">
          Close
        </Button>
      </div>
    </Modal>
  )
}
