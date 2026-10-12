import { Link } from 'react-router'
import { TmdbResultCard } from '@/components/TmdbResultCard'
import { Modal } from '@/components/ui/Modal'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import type { ShowSearchResult, TmdbResult, TmdbSearchResponse } from '@/types/api'

const TMDB_IMG = '/api/images/w185'

export type SearchMode = 'library' | 'tmdb'

/** Label describing why a library hit matched when it was not by title. */
function matchedOnLabel(matchedOn: string): string {
  if (matchedOn === 'path') return 'folder'
  if (matchedOn === 'sys_name') return 'system name'
  return 'alias'
}

function LibraryResults({
  query,
  debouncedQuery,
  searching,
  results,
  onNavigate,
}: {
  query: string
  debouncedQuery: string
  searching: boolean
  results: ShowSearchResult[]
  onNavigate: () => void
}) {
  if (query.trim().length < 2) {
    return (
      <p className="text-sm text-gray-400 dark:text-gray-500">Type at least 2 characters to search your library.</p>
    )
  }
  if (searching || debouncedQuery !== query) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">Searching…</p>
  }
  if (results.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No shows found for &quot;{query}&quot;.</p>
  }
  return (
    <div className="space-y-1.5">
      {results.map((s) => (
        <Link
          key={s.id}
          to={`/shows/${s.id}`}
          onClick={onNavigate}
          className="flex items-center gap-3 px-3 py-2 rounded-lg border hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
        >
          {s.poster_path ? (
            <img src={`${TMDB_IMG}${s.poster_path}`} alt={s.title} className="w-8 h-12 object-cover rounded flex-shrink-0" loading="lazy" />
          ) : (
            <div className="w-8 h-12 bg-gray-100 dark:bg-gray-800 rounded flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate dark:text-gray-100">{s.title}</p>
            <p className="text-xs text-gray-400 dark:text-gray-500">
              {s.release_date?.slice(0, 4)}{s.content_type ? ` · ${s.content_type}` : ''}
              {s.matched_on !== 'title' ? ` · matched ${matchedOnLabel(s.matched_on)}` : ''}
            </p>
          </div>
          <span className="text-xs text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] shrink-0">View →</span>
        </Link>
      ))}
    </div>
  )
}

function TmdbResults({
  query,
  debouncedQuery,
  searching,
  data,
  inLibraryShowId,
  addPending,
  onAdd,
  onNavigate,
  onCardClick,
}: {
  query: string
  debouncedQuery: string
  searching: boolean
  data: TmdbSearchResponse | undefined
  inLibraryShowId: (r: TmdbResult) => number | null
  addPending: boolean
  onAdd: (r: TmdbResult) => void
  onNavigate: () => void
  onCardClick: (r: TmdbResult) => void
}) {
  if (query.trim().length < 2) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">Type at least 2 characters to search TMDB.</p>
  }
  if (searching || debouncedQuery !== query) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">Searching…</p>
  }
  if (!data || data.results.length === 0) {
    return <p className="text-sm text-gray-500 dark:text-gray-400">No results for &quot;{debouncedQuery}&quot;.</p>
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
      {data.results.slice(0, 12).map((r) => (
        <TmdbResultCard
          key={`${r.id}:${r.media_type ?? 'tv'}`}
          result={r}
          inLibraryShowId={inLibraryShowId(r)}
          onAdd={() => onAdd(r)}
          addPending={addPending}
          onNavigate={onNavigate}
          onCardClick={() => onCardClick(r)}
        />
      ))}
    </div>
  )
}

export interface ShowsSearchModalProps {
  mode: SearchMode
  onModeChange: (mode: SearchMode) => void
  query: string
  onQueryChange: (query: string) => void
  debouncedQuery: string
  onClose: () => void
  librarySearching: boolean
  libraryResults: ShowSearchResult[]
  tmdbSearching: boolean
  tmdbData: TmdbSearchResponse | undefined
  inLibraryShowId: (r: TmdbResult) => number | null
  addPending: boolean
  onAdd: (r: TmdbResult) => void
  onCardClick: (r: TmdbResult) => void
}

/**
 * The "Search Shows" modal with its Library / TMDB toggle.
 *
 * Presentational only: the query, mode and both searches stay in the Shows page
 * so they outlive a tab switch and fire exactly when they used to.
 */
export function ShowsSearchModal({
  mode,
  onModeChange,
  query,
  onQueryChange,
  debouncedQuery,
  onClose,
  librarySearching,
  libraryResults,
  tmdbSearching,
  tmdbData,
  inLibraryShowId,
  addPending,
  onAdd,
  onCardClick,
}: ShowsSearchModalProps) {
  return (
    <Modal onClose={onClose} tone="light" maxWidth="2xl" closeOnBackdropClick className="max-h-[80vh] flex flex-col">
      <div className="flex items-center justify-between px-5 py-4 border-b">
        <h3 className="font-semibold dark:text-gray-100">Search Shows</h3>
        <ModalCloseButton onClose={onClose} />
      </div>

      {/* Library / TMDB pill toggle */}
      <div className="px-5 pt-4">
        <div className="flex rounded-lg border text-sm overflow-hidden">
          {(['library', 'tmdb'] as const).map((m) => (
            <button
              key={m}
              onClick={() => onModeChange(m)}
              className={`flex-1 py-2 font-medium transition-colors ${
                mode === m ? 'bg-[var(--color-ocean-600)] text-white' : 'bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'
              }`}
            >
              {m === 'library' ? 'Library' : 'TMDB'}
            </button>
          ))}
        </div>
      </div>

      <div className="px-5 pt-3 pb-3 border-b">
        <input
          type="search"
          autoFocus
          placeholder={mode === 'library' ? 'Search your library…' : 'Search TMDB…'}
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-800 dark:text-gray-100"
        />
      </div>

      <div className="overflow-y-auto flex-1 p-5">
        {mode === 'library' ? (
          <LibraryResults
            query={query}
            debouncedQuery={debouncedQuery}
            searching={librarySearching}
            results={libraryResults}
            onNavigate={onClose}
          />
        ) : (
          <TmdbResults
            query={query}
            debouncedQuery={debouncedQuery}
            searching={tmdbSearching}
            data={tmdbData}
            inLibraryShowId={inLibraryShowId}
            addPending={addPending}
            onAdd={onAdd}
            onNavigate={onClose}
            onCardClick={onCardClick}
          />
        )}
      </div>
    </Modal>
  )
}
