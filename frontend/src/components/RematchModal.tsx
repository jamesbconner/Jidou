import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRematchFile } from '@/hooks/useFiles'
import { useTriggerTask } from '@/hooks/useTasks'
import { useShows } from '@/hooks/useShows'
import { useDebounce } from '@/hooks/useDebounce'
import { api } from '@/api/client'
import type {
  FileRead,
  ShowList,
  TmdbResult,
  TmdbSearchResponse,
  ContentType,
  AppConfig,
} from '@/types/api'

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w300'

interface Props {
  file: FileRead
  onClose: () => void
}

export function RematchModal({ file, onClose }: Props) {
  const [mode, setMode] = useState<'library' | 'tmdb'>('tmdb')
  const initialQuery = file.parsed_show_name ?? ''
  const [searchQuery, setSearchQuery] = useState(initialQuery)
  const debouncedQuery = useDebounce(searchQuery, 300)
  const [selectedLibraryShow, setSelectedLibraryShow] = useState<ShowList | null>(null)
  const [selectedTmdb, setSelectedTmdb] = useState<TmdbResult | null>(null)
  const [contentType, setContentType] = useState<ContentType>('tv')
  const [localPath, setLocalPath] = useState('')
  const [pathEdited, setPathEdited] = useState(false)

  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })
  const { data: allShows = [] } = useShows('title_asc', 10000)

  const { data: tmdbResults, isFetching: tmdbLoading } = useQuery({
    queryKey: ['tmdb-search', debouncedQuery],
    queryFn: () =>
      api.get<TmdbSearchResponse>(
        `/shows/search?query=${encodeURIComponent(debouncedQuery)}&media_type=multi`,
      ),
    enabled: mode === 'tmdb' && searchQuery.length >= 2 && debouncedQuery.length >= 2,
    staleTime: 60_000,
  })

  const rematch = useRematchFile()
  const triggerRoute = useTriggerTask()

  // Library search: filter in-memory for speed
  const libraryResults = useMemo(() => {
    if (searchQuery.trim().length < 2) return []
    const q = searchQuery.toLowerCase()
    return allShows.filter((s) => s.title.toLowerCase().includes(q)).slice(0, 8)
  }, [allShows, searchQuery])

  const tmdbDisplayResults = useMemo(
    () =>
      (tmdbResults?.results ?? [])
        .filter((r) => r.media_type === 'tv' || r.media_type === 'movie')
        .slice(0, 6),
    [tmdbResults],
  )

  // keyed by "tmdb_id:media_type" — TMDB uses separate ID namespaces for tv and movie,
  // so a numeric tmdb_id alone is not unique across types.
  const libraryByTmdbId = useMemo(
    () => new Map(allShows.map((s) => [`${s.tmdb_id}:${s.media_type}`, s])),
    [allShows],
  )

  // When a TMDB result is selected: derive content type from media_type and auto-fill path.
  // Single effect avoids the ordering hazard of two effects sharing selectedTmdb as a dep
  // (the first effect would read stale contentType before the second effect could update it).
  useEffect(() => {
    if (!selectedTmdb || !config) return
    const newType: ContentType = selectedTmdb.media_type === 'movie' ? 'movie' : 'tv'
    setContentType(newType)
    setPathEdited(false)
    const safeTitle = (selectedTmdb.name ?? selectedTmdb.title ?? '')
      .replace(/[\\/:*?"<>|]/g, '_')
      .trim()
    const base = newType === 'movie' ? config.local_movie_path : config.local_tv_path
    setLocalPath(`${base}/${safeTitle}`)
  }, [selectedTmdb, config])

  function handleContentTypeChange(t: ContentType) {
    setContentType(t)
    if (!pathEdited && selectedTmdb && config) {
      const safeTitle = (selectedTmdb.name ?? selectedTmdb.title ?? '')
        .replace(/[\\/:*?"<>|]/g, '_')
        .trim()
      const base =
        t === 'anime'
          ? config.local_anime_path
          : t === 'movie'
            ? config.local_movie_path
            : config.local_tv_path
      setLocalPath(`${base}/${safeTitle}`)
    }
  }

  function switchMode(next: 'library' | 'tmdb') {
    setMode(next)
    setSearchQuery('')
    setSelectedLibraryShow(null)
    setSelectedTmdb(null)
    rematch.reset()
  }

  async function handleConfirm() {
    try {
      if (mode === 'library' && selectedLibraryShow) {
        await rematch.mutateAsync({ id: file.id, payload: { show_id: selectedLibraryShow.id } })
      } else if (mode === 'tmdb' && selectedTmdb) {
        const existing = libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)
        if (existing) {
          await rematch.mutateAsync({ id: file.id, payload: { show_id: existing.id } })
        } else {
          const mediaType =
            selectedTmdb.media_type === 'tv' || selectedTmdb.media_type === 'movie'
              ? selectedTmdb.media_type
              : undefined
          await rematch.mutateAsync({
            id: file.id,
            payload: {
              tmdb_id: selectedTmdb.id,
              tmdb_media_type: mediaType ?? null,
              local_path: localPath || undefined,
              content_type: contentType,
            },
          })
        }
      }
      await triggerRoute.mutateAsync({ task_type: 'route' })
      onClose()
    } catch {
      // rematch.error / triggerRoute.error rendered below
    }
  }

  const canConfirm = (() => {
    if (rematch.isPending || triggerRoute.isPending) return false
    if (mode === 'library') {
      return selectedLibraryShow !== null && selectedLibraryShow.local_path != null
    }
    if (!selectedTmdb) return false
    const existing = libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)
    if (existing) return existing.local_path != null
    return localPath.trim().length > 0
  })()

  const errorMsg = (() => {
    if (rematch.error) {
      return rematch.error instanceof Error ? rematch.error.message : 'Match failed'
    }
    if (triggerRoute.error) {
      return triggerRoute.error instanceof Error
        ? triggerRoute.error.message
        : 'File matched but routing failed — trigger a route task manually'
    }
    return null
  })()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl rounded-lg bg-zinc-900 shadow-xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-700 flex items-center justify-between shrink-0">
          <h2 className="text-sm font-semibold text-zinc-100">Fix show assignment</h2>
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
            {file.show_id && (
              <div className="text-xs text-zinc-500 mt-0.5">Currently assigned to {file.show?.title ?? `show #${file.show_id}`}</div>
            )}
          </div>

          {/* Mode toggle */}
          <div className="flex gap-1 bg-zinc-800 rounded p-1">
            {(['library', 'tmdb'] as const).map((m) => (
              <button
                key={m}
                onClick={() => switchMode(m)}
                className={`flex-1 text-xs py-1.5 rounded transition-colors font-medium ${
                  mode === m ? 'bg-indigo-600 text-white' : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                {m === 'library' ? 'Library' : 'TMDB'}
              </button>
            ))}
          </div>

          {/* Search */}
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={mode === 'library' ? 'Search your library…' : 'Search TMDB…'}
            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
            autoFocus
          />

          {/* Library results */}
          {mode === 'library' && (
            <div className="space-y-1.5">
              {libraryResults.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setSelectedLibraryShow(s)}
                  className={`w-full text-left px-3 py-2 rounded border text-xs transition-colors ${
                    selectedLibraryShow?.id === s.id
                      ? 'border-indigo-500 bg-indigo-950/50'
                      : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
                  }`}
                >
                  <div className="font-medium text-zinc-200">{s.title}</div>
                  <div className="text-zinc-500">
                    #{s.id}
                    {s.local_path ? ` · ${s.local_path}` : ' · no local path set'}
                  </div>
                </button>
              ))}
              {searchQuery.length >= 2 && libraryResults.length === 0 && (
                <div className="text-xs text-zinc-500 py-1">No library shows found.</div>
              )}
              {selectedLibraryShow && !selectedLibraryShow.local_path && (
                <div className="text-xs text-yellow-400 bg-yellow-950/30 border border-yellow-800/40 rounded p-2 mt-1">
                  This show has no local path — set one on the show detail page first.
                </div>
              )}
            </div>
          )}

          {/* TMDB results */}
          {mode === 'tmdb' && (
            <div className="space-y-3">
              {tmdbLoading && (
                <div className="text-xs text-zinc-500 py-1">Searching…</div>
              )}
              {!tmdbLoading && debouncedQuery.length >= 2 && tmdbDisplayResults.length === 0 && (
                <div className="text-xs text-zinc-500 py-1">No results.</div>
              )}

              {searchQuery.length >= 2 && tmdbDisplayResults.length > 0 && (
                <div className="grid grid-cols-3 gap-2">
                  {tmdbDisplayResults.map((r) => (
                    <button
                      key={`${r.id}-${r.media_type}`}
                      onClick={() => setSelectedTmdb(r)}
                      className={`flex flex-col rounded border text-left overflow-hidden transition-colors ${
                        selectedTmdb?.id === r.id && selectedTmdb?.media_type === r.media_type
                          ? 'border-indigo-500 bg-indigo-950/50'
                          : 'border-zinc-700 bg-zinc-800 hover:border-zinc-500'
                      }`}
                    >
                      {r.poster_path ? (
                        <img
                          src={`${TMDB_IMAGE_BASE}${r.poster_path}`}
                          alt={r.name ?? r.title ?? ''}
                          className="w-full aspect-[2/3] object-cover"
                        />
                      ) : (
                        <div className="w-full aspect-[2/3] bg-zinc-700 flex items-center justify-center text-zinc-500 text-xs">
                          No image
                        </div>
                      )}
                      <div className="p-2 space-y-0.5">
                        <div className="text-xs font-medium text-zinc-200 line-clamp-2 leading-tight">
                          {r.name ?? r.title}
                        </div>
                        <div className="text-xs text-zinc-500">
                          {(r.first_air_date ?? r.release_date)?.slice(0, 4)} · {r.media_type}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}

              {/* TMDB selection details */}
              {selectedTmdb && (() => {
                const existing = libraryByTmdbId.get(`${selectedTmdb.id}:${selectedTmdb.media_type ?? ''}`)
                return (
                  <div className="border border-zinc-700 rounded p-3 space-y-3">
                    <div className={`text-xs font-medium ${existing && existing.local_path == null ? 'text-amber-400' : 'text-zinc-300'}`}>
                      {existing
                        ? existing.local_path != null
                          ? `Already in library as show #${existing.id} — will use existing record`
                          : `Already in library as show #${existing.id} — no local path set, configure it in Shows first`
                        : 'Not in library — will create a new show'}
                    </div>
                    {!existing && (
                      <>
                        <div className="space-y-1.5">
                          <div className="text-xs text-zinc-400">Content type</div>
                          <div className="flex gap-4">
                            {(['tv', 'anime', 'movie'] as ContentType[]).map((t) => (
                              <label
                                key={t}
                                className="flex items-center gap-1.5 text-xs text-zinc-300 cursor-pointer"
                              >
                                <input
                                  type="radio"
                                  name="rematch_content_type"
                                  value={t}
                                  checked={contentType === t}
                                  onChange={() => handleContentTypeChange(t)}
                                  className="accent-indigo-500"
                                />
                                {t.charAt(0).toUpperCase() + t.slice(1)}
                              </label>
                            ))}
                          </div>
                        </div>
                        <div className="space-y-1">
                          <div className="text-xs text-zinc-400">Local path</div>
                          <input
                            type="text"
                            value={localPath}
                            onChange={(e) => {
                              setLocalPath(e.target.value)
                              setPathEdited(true)
                            }}
                            placeholder="/media/tv/Show Name"
                            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-1.5 text-xs font-mono text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500"
                          />
                        </div>
                      </>
                    )}
                  </div>
                )
              })()}
            </div>
          )}

          {errorMsg && (
            <div className="text-xs text-red-400 bg-red-950/30 border border-red-800/40 rounded px-3 py-2">
              {errorMsg}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2 shrink-0">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="px-3 py-1.5 text-xs rounded bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {rematch.isPending ? 'Matching…' : 'Match & Route'}
          </button>
        </div>
      </div>
    </div>
  )
}
