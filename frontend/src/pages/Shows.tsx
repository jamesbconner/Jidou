import { useState, useEffect, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ShowCard } from '@/components/ShowCard'
import { useShows, useSearchShows, useCreateShow, SHOW_SORT_LABELS } from '@/hooks/useShows'
import type { ShowSortOrder } from '@/hooks/useShows'
import type { ShowList, TmdbResult } from '@/types/api'

const TMDB_IMG = 'https://image.tmdb.org/t/p/w185'

type Tab = 'library' | 'data'

interface DqCheck {
  key: string
  label: string
  description: string
  test: (s: ShowList) => boolean
}

const DQ_CHECKS: DqCheck[] = [
  {
    key: 'no_path',
    label: 'No local path',
    description: 'Route task cannot place files without a destination path.',
    test: (s) => s.local_path == null,
  },
  {
    key: 'no_content_type',
    label: 'Content type unset',
    description: 'Routing category (Anime / TV / Movie) is required for correct folder placement.',
    test: (s) => s.content_type == null,
  },
  {
    key: 'no_local_episodes',
    label: 'Episodes not synced',
    description: 'No episode records in the local database — run Sync Episodes from the show detail page.',
    test: (s) => s.media_type !== 'movie' && s.episode_count === 0,
  },
  {
    key: 'orphan',
    label: 'No files tracked',
    description: 'TV or anime show with no episodes and no downloaded files — nothing from either the download or import pipeline. May be a stale or accidental library entry.',
    test: (s) => s.media_type !== 'movie' && (s.media_type === 'tv' || s.content_type === 'anime') && s.episode_count === 0 && s.matched_file_count === 0,
  },
]

function applyFilters(
  shows: ShowList[],
  contentType: string,
  status: string,
  genre: string,
  language: string,
  upcoming: boolean,
  minRating: string,
): ShowList[] {
  return shows.filter((s) => {
    if (contentType === '__unset__') { if (s.content_type != null) return false }
    else if (contentType && s.content_type !== contentType) return false

    if (status && s.status !== status) return false

    if (genre && !s.genres?.some((g) => g.name === genre)) return false

    if (language && s.original_language !== language) return false

    if (upcoming && !s.next_episode_to_air) return false

    if (minRating) {
      const min = Number(minRating)
      if (s.vote_average == null || s.vote_average < min) return false
    }

    return true
  })
}

export default function Shows() {
  const [tab, setTab] = useState<Tab>('library')
  const [dqFilter, setDqFilter] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [sort, setSort] = useState<ShowSortOrder>('title_asc')

  const [filterContentType, setFilterContentType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterGenre, setFilterGenre] = useState('')
  const [filterLanguage, setFilterLanguage] = useState('')
  const [filterUpcoming, setFilterUpcoming] = useState(false)
  const [filterMinRating, setFilterMinRating] = useState('')

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setDebouncedQuery(query), 300)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [query])

  const { data: shows = [], isLoading } = useShows(sort)
  const { data: searchData } = useSearchShows(debouncedQuery)
  const createShow = useCreateShow()

  const genreOptions = useMemo(() => {
    const names = new Set<string>()
    shows.forEach((s) => s.genres?.forEach((g) => { if (g.name) names.add(g.name as string) }))
    return Array.from(names).sort()
  }, [shows])

  const languageOptions = useMemo(() => {
    const langs = new Set<string>()
    shows.forEach((s) => { if (s.original_language) langs.add(s.original_language) })
    return Array.from(langs).sort()
  }, [shows])

  const statusOptions = useMemo(() => {
    const statuses = new Set<string>()
    shows.forEach((s) => { if (s.status) statuses.add(s.status) })
    return Array.from(statuses).sort()
  }, [shows])

  const filtered = useMemo(
    () => applyFilters(shows, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating),
    [shows, filterContentType, filterStatus, filterGenre, filterLanguage, filterUpcoming, filterMinRating],
  )

  const dqCounts = useMemo(
    () => Object.fromEntries(DQ_CHECKS.map((c) => [c.key, shows.filter(c.test).length])),
    [shows],
  )
  const totalDqIssues = useMemo(
    () => shows.filter((s) => DQ_CHECKS.some((c) => c.test(s))).length,
    [shows],
  )
  const dqRows = useMemo(() => {
    const check = dqFilter ? DQ_CHECKS.find((c) => c.key === dqFilter) : null
    return check
      ? shows.filter(check.test)
      : shows.filter((s) => DQ_CHECKS.some((c) => c.test(s)))
  }, [shows, dqFilter])

  const activeFilterCount = [
    filterContentType, filterStatus, filterGenre, filterLanguage, filterMinRating,
  ].filter(Boolean).length + (filterUpcoming ? 1 : 0)

  function clearFilters() {
    setFilterContentType('')
    setFilterStatus('')
    setFilterGenre('')
    setFilterLanguage('')
    setFilterUpcoming(false)
    setFilterMinRating('')
  }

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
      genre_ids: r.genre_ids ?? null,
      origin_country: r.origin_country ?? null,
    })
  }

  const selectCls = 'border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500'
  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? 'border-blue-600 text-blue-600'
        : 'border-transparent text-gray-500 hover:text-gray-700'
    }`

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold mr-auto">Shows</h1>
        {tab === 'library' && activeFilterCount > 0 && (
          <button
            onClick={clearFilters}
            className="text-xs border border-gray-300 rounded px-2 py-1 hover:bg-gray-100"
          >
            Clear filters ({activeFilterCount})
          </button>
        )}
        {tab === 'library' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as ShowSortOrder)} className={selectCls}>
            {(Object.entries(SHOW_SORT_LABELS) as [ShowSortOrder, string][]).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        )}
        <input
          type="search"
          placeholder="Search TMDB…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm w-64 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* Tabs */}
      <div className="flex border-b">
        <button className={tabCls('library')} onClick={() => setTab('library')}>
          Shows in Library ({shows.length})
        </button>
        <button className={tabCls('data')} onClick={() => setTab('data')}>
          Data Quality
          {totalDqIssues > 0 && (
            <span className="ml-2 bg-amber-100 text-amber-700 text-xs rounded-full px-1.5 py-0.5">
              {totalDqIssues}
            </span>
          )}
        </button>
      </div>

      {tab === 'library' && (
        <>
          {/* Filter bar */}
          <div className="flex items-center gap-3 flex-wrap bg-gray-50 border rounded-lg px-4 py-3">
            <span className="text-xs font-medium text-gray-500 shrink-0">Filter</span>

            <select value={filterContentType} onChange={(e) => setFilterContentType(e.target.value)} className={selectCls}>
              <option value="">All types</option>
              <option value="anime">Anime</option>
              <option value="tv">TV</option>
              <option value="movie">Movie</option>
              <option value="__unset__">Unset</option>
            </select>

            {statusOptions.length > 0 && (
              <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className={selectCls}>
                <option value="">All statuses</option>
                {statusOptions.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            )}

            {genreOptions.length > 0 && (
              <select value={filterGenre} onChange={(e) => setFilterGenre(e.target.value)} className={selectCls}>
                <option value="">All genres</option>
                {genreOptions.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            )}

            {languageOptions.length > 0 && (
              <select value={filterLanguage} onChange={(e) => setFilterLanguage(e.target.value)} className={selectCls}>
                <option value="">All languages</option>
                {languageOptions.map((l) => <option key={l} value={l}>{l.toUpperCase()}</option>)}
              </select>
            )}

            <select value={filterMinRating} onChange={(e) => setFilterMinRating(e.target.value)} className={selectCls}>
              <option value="">Any rating</option>
              <option value="6">6+</option>
              <option value="7">7+</option>
              <option value="8">8+</option>
              <option value="9">9+</option>
            </select>

            <label className="flex items-center gap-1.5 text-sm cursor-pointer">
              <input
                type="checkbox"
                checked={filterUpcoming}
                onChange={(e) => setFilterUpcoming(e.target.checked)}
                className="rounded"
              />
              <span className="text-gray-700">Upcoming episode</span>
            </label>
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
                        Add to Library
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Library grid */}
          <section>
            <p className="text-xs text-gray-500 mb-2">
              {activeFilterCount > 0 ? `${filtered.length} of ${shows.length} shows` : `${shows.length} show${shows.length !== 1 ? 's' : ''}`}
            </p>
            {isLoading ? (
              <p className="text-gray-400 text-sm">Loading…</p>
            ) : filtered.length === 0 ? (
              <p className="text-gray-500 text-sm">
                {shows.length === 0 ? 'No shows in library yet. Search above to add one.' : 'No shows match the current filters.'}
              </p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                {filtered.map((s) => (
                  <ShowCard key={s.id} show={s} />
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {tab === 'data' && isLoading && (
        <p className="text-gray-400 text-sm">Loading…</p>
      )}

      {tab === 'data' && !isLoading && (
        <section className="space-y-6">
          {/* Metric summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {DQ_CHECKS.map((c) => {
              const count = dqCounts[c.key] ?? 0
              const active = dqFilter === c.key
              return (
                <button
                  key={c.key}
                  title={c.description}
                  onClick={() => setDqFilter(active ? null : c.key)}
                  className={`text-left rounded-lg border p-3 transition-colors ${
                    active
                      ? 'border-amber-400 bg-amber-50'
                      : count > 0
                        ? 'border-amber-200 bg-white hover:bg-amber-50'
                        : 'border-gray-200 bg-white hover:bg-gray-50'
                  }`}
                >
                  <p className={`text-2xl font-bold ${count > 0 ? 'text-amber-600' : 'text-gray-400'}`}>
                    {count}
                  </p>
                  <p className="text-xs text-gray-600 mt-0.5 leading-tight">{c.label}</p>
                </button>
              )
            })}
          </div>

          {/* Active filter description */}
          {dqFilter && (() => {
            const check = DQ_CHECKS.find((c) => c.key === dqFilter)!
            return (
              <p className="text-xs text-gray-500 flex items-center gap-2">
                <span className="font-medium text-gray-700">{check.label}:</span>
                {check.description}
                <button onClick={() => setDqFilter(null)} className="ml-2 text-blue-600 hover:underline">
                  Show all issues
                </button>
              </p>
            )
          })()}

          {/* Issue table */}
          {dqRows.length === 0 ? (
            <p className="text-sm text-gray-500">
              {dqFilter
                ? `No shows with this issue.`
                : `No data quality issues found across ${shows.length} show${shows.length !== 1 ? 's' : ''}.`}
            </p>
          ) : (
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b">
                  <th className="pb-2 pr-4 font-medium">Title</th>
                  <th className="pb-2 font-medium">Issues</th>
                </tr>
              </thead>
              <tbody>
                {dqRows.map((s) => {
                  const issues = DQ_CHECKS.filter((c) => c.test(s))
                  return (
                    <tr key={s.id} className="border-b last:border-0 hover:bg-gray-50">
                      <td className="py-2 pr-4 whitespace-nowrap">
                        <Link to={`/shows/${s.id}`} className="text-blue-600 hover:underline font-medium">
                          {s.title}
                        </Link>
                        <span className="ml-2 text-xs text-gray-400 capitalize">{s.content_type ?? s.media_type}</span>
                      </td>
                      <td className="py-2">
                        <div className="flex gap-2 flex-wrap">
                          {issues.map((c) => (
                            <button
                              key={c.key}
                              title={c.description}
                              onClick={() => setDqFilter(c.key)}
                              className="bg-amber-100 text-amber-700 text-xs rounded px-1.5 py-0.5 hover:bg-amber-200"
                            >
                              {c.label}
                            </button>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  )
}
