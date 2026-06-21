import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { useTmdbSuggestions, useRematchFile } from '@/hooks/useFiles'
import type { FileRead, TmdbSuggestion, TmdbSearchResponse, ContentType, AppConfig } from '@/types/api'

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w185'

interface Props {
  file: FileRead
  onClose: () => void
}

export function ResolveFileModal({ file, onClose }: Props) {
  const [selected, setSelected] = useState<TmdbSuggestion | null>(null)
  const [contentType, setContentType] = useState<ContentType>('tv')
  const [localPath, setLocalPath] = useState('')
  const [searchQuery, setSearchQuery] = useState(file.parsed_show_name ?? '')
  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery)
  const [customSearch, setCustomSearch] = useState(false)
  const [pathEdited, setPathEdited] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })

  const { data: suggestions, isFetching: suggestionsLoading } = useTmdbSuggestions(
    customSearch ? null : file.id,
  )

  const { data: searchResults, isFetching: searchLoading } = useQuery({
    queryKey: ['tmdb-search', debouncedQuery],
    queryFn: async () => {
      if (!debouncedQuery.trim() || debouncedQuery.length < 2) return null
      return api.get<TmdbSearchResponse>(
        `/shows/search?query=${encodeURIComponent(debouncedQuery)}&media_type=multi`,
      )
    },
    enabled: customSearch && debouncedQuery.length >= 2,
    staleTime: 60_000,
  })

  const rematch = useRematchFile()

  // Build TMDB suggestion shape from raw TMDB search results (which use TmdbResult shape)
  const searchAsSuggestions: TmdbSuggestion[] = (searchResults?.results ?? [])
    .filter((r) => r.media_type === 'tv' || r.media_type === 'movie')
    .slice(0, 6)
    .map((r) => ({
      tmdb_id: r.id,
      title: r.name ?? r.title ?? null,
      media_type: r.media_type ?? null,
      overview: r.overview,
      poster_path: r.poster_path,
      first_air_date: r.first_air_date ?? r.release_date ?? null,
      vote_average: r.vote_average,
    }))

  const displayResults = customSearch ? searchAsSuggestions : (suggestions?.results ?? [])
  const isLoading = customSearch ? searchLoading : suggestionsLoading

  // Suggest local path when selection or content type changes, but not if the
  // user has already typed a custom path (pathEdited guard).  Changing the
  // selected show resets pathEdited so the suggestion updates automatically.
  useEffect(() => {
    if (!selected || !config || pathEdited) return
    const safeTitle = (selected.title ?? '').replace(/[\\/:*?"<>|]/g, '_').trim()
    const base =
      contentType === 'anime'
        ? config.local_anime_path
        : contentType === 'movie'
          ? config.local_movie_path
          : config.local_tv_path
    setLocalPath(`${base}/${safeTitle}`)
  }, [selected, contentType, config, pathEdited])

  // Debounce manual search input
  useEffect(() => {
    if (!customSearch) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setDebouncedQuery(searchQuery), 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [searchQuery, customSearch])

  // Snap content type to match the TMDB media type on every selection change.
  // Anime requires manual override after selection.
  // Also reset pathEdited so the path suggestion updates for the new show.
  useEffect(() => {
    if (!selected) return
    setContentType(selected.media_type === 'movie' ? 'movie' : 'tv')
    setPathEdited(false)
  }, [selected])

  function handleConfirm() {
    if (!selected) return
    rematch.mutate(
      {
        id: file.id,
        payload: {
          tmdb_id: selected.tmdb_id,
          tmdb_media_type: (selected.media_type === 'tv' || selected.media_type === 'movie')
            ? selected.media_type
            : undefined,
          local_path: localPath || undefined,
          content_type: contentType,
        },
      },
      { onSuccess: onClose },
    )
  }

  function handleReset() {
    rematch.mutate({ id: file.id, payload: {} }, { onSuccess: onClose })
  }

  const year = (date: string | null | undefined) =>
    date ? new Date(date).getFullYear().toString() : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl rounded-lg bg-zinc-900 shadow-xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-100">Resolve unmatched file</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-lg leading-none">✕</button>
        </div>

        <div className="overflow-y-auto flex-1 px-5 py-4 space-y-5">
          {/* File info */}
          <div className="bg-zinc-800 rounded p-3 space-y-1">
            <div className="text-xs text-zinc-400">Filename</div>
            <div className="font-mono text-xs text-zinc-200 truncate">{file.original_filename}</div>
            {file.parsed_show_name && (
              <>
                <div className="text-xs text-zinc-400 mt-1">Parsed as</div>
                <div className="text-xs text-zinc-300">{file.parsed_show_name}</div>
              </>
            )}
          </div>

          {/* Search */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs text-zinc-400">Search TMDB</label>
              {!customSearch && (
                <button
                  onClick={() => {
                    setCustomSearch(true)
                    setSearchQuery(file.parsed_show_name ?? '')
                    setDebouncedQuery(file.parsed_show_name ?? '')
                  }}
                  className="text-xs text-indigo-400 hover:text-indigo-300"
                >
                  refine search
                </button>
              )}
            </div>
            {customSearch && (
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search TMDB..."
                className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
              />
            )}
          </div>

          {/* TMDB results grid */}
          <div className="space-y-2">
            {isLoading && (
              <div className="text-xs text-zinc-500 py-2">Loading suggestions…</div>
            )}
            {!isLoading && displayResults.length === 0 && (
              <div className="text-xs text-zinc-500 py-2">No results found.</div>
            )}
            <div className="grid grid-cols-3 gap-2">
              {displayResults.map((r) => (
                <button
                  key={`${r.tmdb_id}-${r.media_type}`}
                  onClick={() => setSelected(r)}
                  className={`flex flex-col rounded border text-left overflow-hidden transition-colors ${
                    selected?.tmdb_id === r.tmdb_id && selected?.media_type === r.media_type
                      ? 'border-indigo-500 bg-indigo-950/50'
                      : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
                  }`}
                >
                  {r.poster_path ? (
                    <img
                      src={`${TMDB_IMAGE_BASE}${r.poster_path}`}
                      alt={r.title ?? ''}
                      className="w-full aspect-[2/3] object-cover"
                    />
                  ) : (
                    <div className="w-full aspect-[2/3] bg-zinc-700 flex items-center justify-center text-zinc-500 text-xs">
                      No image
                    </div>
                  )}
                  <div className="p-2 space-y-0.5">
                    <div className="text-xs font-medium text-zinc-200 line-clamp-2 leading-tight">
                      {r.title}
                    </div>
                    <div className="text-xs text-zinc-500">
                      {year(r.first_air_date)} · {r.media_type}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Selected show details + path config */}
          {selected && (
            <div className="border border-zinc-700 rounded p-3 space-y-3">
              <div className="text-xs font-medium text-zinc-300">
                Selected: {selected.title} ({year(selected.first_air_date)})
              </div>

              {/* Content type */}
              <div className="space-y-1">
                <label className="text-xs text-zinc-400">Content type</label>
                <div className="flex gap-3">
                  {(['tv', 'anime', 'movie'] as ContentType[]).map((t) => (
                    <label key={t} className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer">
                      <input
                        type="radio"
                        name="content_type"
                        value={t}
                        checked={contentType === t}
                        onChange={() => setContentType(t)}
                        className="accent-indigo-500"
                      />
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </label>
                  ))}
                </div>
              </div>

              {/* Local path */}
              <div className="space-y-1">
                <label className="text-xs text-zinc-400">Local path</label>
                <input
                  type="text"
                  value={localPath}
                  onChange={(e) => { setLocalPath(e.target.value); setPathEdited(true) }}
                  placeholder="/media/tv/Show Name"
                  className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
                />
                <div className="text-xs text-zinc-500">
                  Files will be placed in Season NN/ subdirectories under this path.
                </div>
              </div>
            </div>
          )}

          {/* Error */}
          {rematch.isError && (
            <div className="text-xs text-red-400 bg-red-950/30 rounded p-2">
              {rematch.error instanceof Error ? rematch.error.message : 'Match failed'}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex items-center justify-between">
          <button
            onClick={handleReset}
            disabled={rematch.isPending}
            className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-50"
          >
            Reset for auto re-match
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700"
            >
              Cancel
            </button>
            <button
              onClick={handleConfirm}
              disabled={!selected || !localPath || rematch.isPending}
              className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {rematch.isPending ? 'Matching…' : 'Confirm match'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
