import { useState, useEffect, useRef } from 'react'
import { useRematchShow, useSearchShows } from '@/hooks/useShows'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import type { TmdbResult } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w185'

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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-2xl mx-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold">Change TMDB Match</h3>
          <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">
            Cancel
          </button>
        </div>
        <input
          type="search"
          placeholder="Search TMDB…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
          className="border rounded px-3 py-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {rematch.isError && (
          <p className="text-xs text-red-600">{(rematch.error as Error).message}</p>
        )}
        {debouncedQuery.length >= 2 && searchData && searchData.results.length > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
            {searchData.results.slice(0, 12).map((r) => (
              <button
                key={`${r.media_type ?? 'unknown'}-${r.id}`}
                onClick={() => handlePick(r)}
                disabled={rematch.isPending || r.id === currentTmdbId}
                className="text-left bg-white rounded shadow overflow-hidden hover:ring-2 hover:ring-blue-400 disabled:opacity-40 transition border"
              >
                {r.poster_path ? (
                  <img
                    src={`${TMDB_IMG}${r.poster_path}`}
                    alt={r.name ?? r.title ?? ''}
                    className="w-full h-28 object-cover"
                    loading="lazy"
                  />
                ) : (
                  <div className="w-full h-28 bg-gray-100 flex items-center justify-center text-gray-400 text-xs">
                    No image
                  </div>
                )}
                <div className="p-1">
                  <p className="text-xs line-clamp-2 leading-tight">{r.name ?? r.title}</p>
                  {r.id === currentTmdbId && (
                    <p className="text-xs text-green-600 font-medium">Current</p>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
        {rematch.isPending && (
          <p className="text-xs text-gray-500">Re-matching… episodes are being synced.</p>
        )}
      </div>
      {pendingPick && (
        <ConfirmDialog
          title="Change TMDB match?"
          description={`Re-match to "${pendingPick.name ?? pendingPick.title}"? This will replace all episode data for this show.`}
          confirmLabel="Re-match"
          onConfirm={handleConfirmRematch}
          onCancel={() => setPendingPick(null)}
        />
      )}
    </div>
  )
}
