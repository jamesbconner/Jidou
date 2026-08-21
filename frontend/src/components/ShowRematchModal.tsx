import { useState, useEffect, useRef } from 'react'
import { useRematchShow, useSearchShows } from '@/hooks/useShows'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { Modal } from '@/components/ui/Modal'
import type { TmdbResult } from '@/types/api'

const TMDB_IMG = '/api/images/w185'

export function ShowRematchModal({
  showId,
  currentTmdbId,
  onClose,
}: {
  showId: number
  currentTmdbId: number
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [pendingPick, setPendingPick] = useState<TmdbResult | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const rematch = useRematchShow(showId)

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(query), 300)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [query])

  const { data: searchData } = useSearchShows(debouncedQuery)

  function handlePick(r: TmdbResult) {
    if (r.id === currentTmdbId) return
    setPendingPick(r)
  }

  function handleConfirmRematch() {
    if (!pendingPick) return
    rematch.mutate(
      { tmdbId: pendingPick.id, mediaType: pendingPick.media_type ?? 'tv' },
      { onSuccess: () => onClose() },
    )
    setPendingPick(null)
  }

  return (
    <Modal onClose={onClose} tone="light" maxWidth="2xl" className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">Change TMDB Match</h3>
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200">
            Cancel
          </button>
        </div>
        <input
          type="search"
          placeholder="Search TMDB…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          className="border rounded px-3 py-2 text-sm w-full dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {rematch.isError && (
          <p className="text-xs text-red-600 dark:text-red-400">{(rematch.error as Error).message}</p>
        )}
        {debouncedQuery.length >= 2 && searchData && searchData.results.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
            {searchData.results.slice(0, 12).map((r) => (
              <button
                key={`${r.media_type ?? 'unknown'}-${r.id}`}
                onClick={() => handlePick(r)}
                disabled={rematch.isPending || r.id === currentTmdbId}
                className="text-left bg-white dark:bg-gray-800 rounded shadow overflow-hidden hover:ring-2 hover:ring-blue-400 disabled:opacity-40 transition border dark:border-gray-700"
              >
                {r.poster_path ? (
                  <img
                    src={`${TMDB_IMG}${r.poster_path}`}
                    alt={r.name ?? r.title ?? ''}
                    className="w-full aspect-[2/3] object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full aspect-[2/3] bg-gray-100 dark:bg-gray-700 flex items-center justify-center text-gray-400 dark:text-gray-500 text-xs">
                    No image
                  </div>
                )}
                <div className="p-1">
                  <p className="text-xs line-clamp-2 leading-tight text-gray-900 dark:text-gray-100">{r.name ?? r.title}</p>
                  {r.id === currentTmdbId && (
                    <p className="text-xs text-green-600 dark:text-green-400 font-medium">Current</p>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
        {rematch.isPending && (
          <p className="text-xs text-gray-500 dark:text-gray-400">Re-matching… episodes are being synced.</p>
        )}
      {pendingPick && (
        <ConfirmDialog
          title="Change TMDB match?"
          description={`Re-match to "${pendingPick.name ?? pendingPick.title}"? This will replace all episode data for this show.`}
          confirmLabel="Re-match"
          onConfirm={handleConfirmRematch}
          onCancel={() => setPendingPick(null)}
        />
      )}
    </Modal>
  )
}
