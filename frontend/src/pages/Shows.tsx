import { useState, useEffect, useRef } from 'react'
import { ShowCard } from '@/components/ShowCard'
import { useShows, useSearchShows, useCreateShow } from '@/hooks/useShows'
import type { TmdbResult } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w185'

export default function Shows() {
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(query), 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query])

  const { data: shows = [], isLoading } = useShows()
  const { data: searchData } = useSearchShows(debouncedQuery)
  const createShow = useCreateShow()

  function handleTrack(r: TmdbResult) {
    createShow.mutate({
      tmdb_id: r.id,
      title: r.name ?? r.title ?? 'Unknown',
      media_type: r.media_type ?? 'tv',
      overview: r.overview,
      poster_path: r.poster_path,
      backdrop_path: r.backdrop_path,
      vote_average: r.vote_average,
      vote_count: r.vote_count,
      release_date: r.first_air_date ?? r.release_date,
      original_language: r.original_language,
    })
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Shows</h1>
        <input
          type="search"
          placeholder="Search TMDB…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* TMDB search results */}
      {debouncedQuery.length >= 2 && searchData && searchData.results.length > 0 && (
        <section>
          <h2 className="text-sm font-medium text-gray-500 mb-2">TMDB Results</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            {searchData.results.slice(0, 12).map((r) => (
              <div key={r.id} className="bg-white rounded-lg shadow overflow-hidden">
                {r.poster_path ? (
                  <img src={`${TMDB_IMG}${r.poster_path}`} alt={r.name ?? r.title} className="w-full h-36 object-cover" loading="lazy" />
                ) : (
                  <div className="w-full h-36 bg-gray-100 flex items-center justify-center text-gray-400 text-xs">No image</div>
                )}
                <div className="p-2">
                  <p className="text-xs font-medium line-clamp-2">{r.name ?? r.title}</p>
                  <button
                    onClick={() => handleTrack(r)}
                    disabled={createShow.isPending}
                    className="mt-1 w-full text-xs bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:opacity-50"
                  >
                    Track
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Tracked shows */}
      <section>
        <h2 className="text-sm font-medium text-gray-500 mb-2">
          Tracked Shows ({shows.length})
        </h2>
        {isLoading ? (
          <p className="text-gray-400 text-sm">Loading…</p>
        ) : shows.length === 0 ? (
          <p className="text-gray-500 text-sm">No shows tracked yet. Search above to add one.</p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
            {shows.map((s) => (
              <ShowCard key={s.id} show={s} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
