import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  useAddShowFromFeed,
  useSuggestFeedRegex,
  useTestFeedRegex,
} from '@/hooks/useRss'
import { useLibraryIndex, useLocalShowSearch, useTmdbSearch } from '@/hooks/useShows'
import { useDebounce } from '@/hooks/useDebounce'
import { buildShowCreatePayload } from '@/utils/buildShowCreatePayload'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/Field'
import type {
  FeedAddShowResult,
  FeedEntryGroupRead,
  RegexMatchReportRead,
  RssFeedRead,
  TmdbResult,
} from '@/types/api'

type Pick =
  | { kind: 'library'; id: number; title: string }
  | { kind: 'tmdb'; result: TmdbResult }

interface Option {
  key: string
  label: string
  detail: string
  pick: Pick
}

const INPUT =
  'w-full border border-gray-300 dark:border-gray-600 rounded px-2 py-1.5 text-sm bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)]'

function tmdbTitle(r: TmdbResult): string {
  return r.name ?? r.title ?? 'Unknown'
}

function pickTitle(p: Pick): string {
  return p.kind === 'library' ? p.title : tmdbTitle(p.result)
}

function isSamePick(a: Pick | null, b: Pick): boolean {
  if (a === null || a.kind !== b.kind) return false
  if (a.kind === 'library') return a.id === (b as typeof a).id
  // A movie and a TV show can share a TMDB id, so identity includes media_type.
  const other = (b as typeof a).result
  return a.result.id === other.id && a.result.media_type === other.media_type
}

/** "N of M titles selected" copy for a match report, with the empty-include caveat. */
export function matchSummary(report: RegexMatchReportRead | null, includeEmpty: boolean): string {
  if (includeEmpty) {
    return 'No include pattern — YaRSS2 will not select any release until one is set.'
  }
  if (!report) return 'Checking against the feed…'
  const n = report.matched_titles.length
  return `${n} of ${report.total} current ${report.total === 1 ? 'title' : 'titles'} selected`
}

/**
 * Inline pane that adds a feed group's show to the library (or picks one
 * already there) and creates its subscription in one step, with the LLM
 * having seen the feed's real release titles.
 */
export function AddShowFromFeedPane({
  feed,
  group,
  onDone,
  onAdded,
}: {
  feed: RssFeedRead
  group: FeedEntryGroupRead
  onDone?: () => void
  /** Called once the add succeeds, so the parent can keep this row on screen. */
  onAdded?: () => void
}) {
  const parsedName = group.parsed_name ?? ''
  const [query, setQuery] = useState(parsedName)
  const debouncedQuery = useDebounce(query.trim(), 300)
  const [pick, setPick] = useState<Pick | null>(
    group.library_show
      ? { kind: 'library', id: group.library_show.id, title: group.library_show.title }
      : null,
  )
  const [include, setInclude] = useState('')
  const [exclude, setExclude] = useState('')
  const [ignoreInclude, setIgnoreInclude] = useState(true)
  const [ignoreExclude, setIgnoreExclude] = useState(true)
  const [previous, setPrevious] = useState<string[]>([])
  const [name, setName] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [match, setMatch] = useState<RegexMatchReportRead | null>(null)
  const [result, setResult] = useState<FeedAddShowResult | null>(null)
  const autoSuggested = useRef(false)

  const library = useLocalShowSearch(debouncedQuery, 6)
  const tmdb = useTmdbSearch(debouncedQuery, 'multi')
  const libraryIndex = useLibraryIndex()
  const suggest = useSuggestFeedRegex(feed.id)
  const testRegex = useTestFeedRegex(feed.id)
  const add = useAddShowFromFeed(feed.id)

  const options = useMemo<Option[]>(() => {
    const seen = new Set<number>()
    const out: Option[] = []
    for (const s of library.data ?? []) {
      seen.add(s.id)
      out.push({
        key: `lib-${s.id}`,
        label: s.title,
        detail: 'In your library',
        pick: { kind: 'library', id: s.id, title: s.title },
      })
    }
    for (const r of (tmdb.data?.results ?? []).slice(0, 6)) {
      const mediaType = r.media_type
      if (mediaType !== 'tv' && mediaType !== 'movie') continue
      const inLibrary = libraryIndex.get(`${r.id}:${mediaType}`)
      if (inLibrary) {
        if (seen.has(inLibrary.id)) continue
        seen.add(inLibrary.id)
        out.push({
          key: `lib-${inLibrary.id}`,
          label: inLibrary.title,
          detail: 'In your library',
          pick: { kind: 'library', id: inLibrary.id, title: inLibrary.title },
        })
        continue
      }
      const year = (r.first_air_date ?? r.release_date ?? '').slice(0, 4)
      out.push({
        key: `tmdb-${mediaType}-${r.id}`,
        label: tmdbTitle(r),
        detail: `TMDB · ${mediaType === 'tv' ? 'TV' : 'Movie'}${year ? ` · ${year}` : ''}`,
        pick: { kind: 'tmdb', result: r },
      })
    }
    return out
  }, [library.data, tmdb.data, libraryIndex])

  // Suggest once, as soon as a show is chosen, so the common case needs no click.
  const runSuggest = (showTitle: string, prev: string[]) => {
    suggest.mutate(
      { parsed_name: parsedName, show_title: showTitle, previous: prev },
      {
        onSuccess: (s) => {
          setInclude(s.regex_include)
          setExclude(s.regex_exclude)
          setMatch(s.match)
          setPrevious((p) => (p.includes(s.regex_include) ? p : [...p, s.regex_include].slice(-5)))
        },
      },
    )
  }
  useEffect(() => {
    if (pick && !autoSuggested.current && parsedName) {
      autoSuggested.current = true
      runSuggest(pickTitle(pick), [])
    }
    // runSuggest only closes over stable mutation handles and parsedName.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pick])

  // Live preview of hand edits against the feed's current titles.
  const debouncedInclude = useDebounce(include, 500)
  const debouncedExclude = useDebounce(exclude, 500)
  const lastTested = useRef<string>('')
  useEffect(() => {
    if (!parsedName || !pick) return
    // Both empty: the answer is known (an empty include selects nothing), and
    // firing here would only race the initial LLM suggestion.
    if (!debouncedInclude && !debouncedExclude) return
    const key = JSON.stringify([debouncedInclude, debouncedExclude, ignoreInclude, ignoreExclude])
    if (key === lastTested.current) return
    lastTested.current = key
    testRegex.mutate(
      {
        parsed_name: parsedName,
        regex_include: debouncedInclude || null,
        regex_exclude: debouncedExclude || null,
        regex_include_ignorecase: ignoreInclude,
        regex_exclude_ignorecase: ignoreExclude,
      },
      { onSuccess: setMatch },
    )
    // testRegex.mutate is stable; including the mutation object would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedInclude, debouncedExclude, ignoreInclude, ignoreExclude, parsedName, pick])

  const submit = () => {
    if (!pick) return
    add.mutate(
      {
        parsed_name: parsedName,
        ...(pick.kind === 'library'
          ? { show_id: pick.id }
          : { show: buildShowCreatePayload(pick.result) }),
        name: name.trim() || null,
        regex_include: include || null,
        regex_exclude: exclude || null,
        regex_include_ignorecase: ignoreInclude,
        regex_exclude_ignorecase: ignoreExclude,
        enabled,
      },
      {
        onSuccess: (r) => {
          setResult(r)
          onAdded?.()
        },
      },
    )
  }

  if (result) {
    const title = result.show?.title ?? pickTitle(pick as Pick)
    return (
      <div role="status" className="mt-2 rounded border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 p-3 text-sm text-green-800 dark:text-green-200">
        <p className="font-medium">
          {result.show_created ? `Added “${title}” to your library` : `Using “${title}” from your library`}
          {result.subscription_created
            ? ' and created its subscription.'
            : result.adopted_stub
              ? ' and linked its existing subscription to this feed.'
              : ' — it was already subscribed to this feed.'}
        </p>
        <p className="mt-1 text-xs">
          {result.subscription_created || result.adopted_stub
            ? enabled
              ? 'It will be included the next time you publish.'
              : 'It is saved in Jidou only; enable it to include it in the next publish.'
            : 'Nothing was changed.'}
          {result.alias_added && ` “${parsedName}” was added as an alias.`}
        </p>
        <div className="mt-2 flex items-center gap-3">
          {result.show && (
            <Link
              to={`/shows/${result.show.id}`}
              className="text-xs text-[var(--color-ocean-700)] dark:text-[var(--color-ocean-300)] hover:underline"
            >
              Open show
            </Link>
          )}
          {onDone && (
            <button onClick={onDone} className="text-xs text-gray-600 dark:text-gray-300 hover:underline">
              Close
            </button>
          )}
        </div>
      </div>
    )
  }

  const includeEmpty = include.trim() === ''
  const error = add.error ?? suggest.error ?? testRegex.error

  return (
    <div className="mt-2 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 p-3 space-y-4">
      <section aria-label="Show" className="space-y-2">
        <Field
          label="Show"
          note="Pick the library or TMDB show these releases belong to. The feed's name is taught as an alias."
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search your library and TMDB"
            aria-label="Search for the show"
            className={INPUT}
          />
        </Field>
        {pick && (
          <p className="text-xs text-gray-700 dark:text-gray-200">
            Selected: <strong>{pickTitle(pick)}</strong>
            {pick.kind === 'tmdb' && ' (will be added to your library)'}
          </p>
        )}
        {debouncedQuery.length >= 2 && (library.isLoading || tmdb.isLoading) && (
          <p className="text-xs text-gray-500 dark:text-gray-400">Searching…</p>
        )}
        {options.length > 0 && (
          <ul role="listbox" aria-label="Show matches" className="space-y-1">
            {options.map((o) => {
              const selected = isSamePick(pick, o.pick)
              return (
                <li key={o.key}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => setPick(o.pick)}
                    className={`w-full text-left rounded border px-2 py-1.5 text-sm ${
                      selected
                        ? 'border-[var(--color-ocean-500)] bg-[var(--color-ocean-100)] dark:bg-[var(--color-ocean-900)]/40'
                        : 'border-gray-200 dark:border-gray-700 hover:bg-white dark:hover:bg-gray-800'
                    }`}
                  >
                    <span className="font-medium text-gray-900 dark:text-gray-100">{o.label}</span>
                    <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">{o.detail}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {pick && (
        <section aria-label="Filter" className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-600 dark:text-gray-300">Filter</span>
            <Button
              variant="secondary"
              tone="light"
              size="sm"
              onClick={() => runSuggest(pickTitle(pick), previous)}
              disabled={suggest.isPending}
            >
              {suggest.isPending ? 'Suggesting…' : previous.length ? 'Re-suggest' : 'Suggest filter'}
            </Button>
          </div>
          <Field label="Include (regex)">
            <input
              value={include}
              onChange={(e) => setInclude(e.target.value)}
              aria-label="Include regex"
              className={`${INPUT} font-mono`}
            />
          </Field>
          <Field label="Exclude (regex, optional)">
            <input
              value={exclude}
              onChange={(e) => setExclude(e.target.value)}
              aria-label="Exclude regex"
              className={`${INPUT} font-mono`}
            />
          </Field>
          <div className="flex gap-4 text-xs text-gray-600 dark:text-gray-300">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={ignoreInclude} onChange={(e) => setIgnoreInclude(e.target.checked)} />
              Ignore case (include)
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={ignoreExclude} onChange={(e) => setIgnoreExclude(e.target.checked)} />
              Ignore case (exclude)
            </label>
          </div>
          <p
            aria-live="polite"
            className={`text-xs ${includeEmpty ? 'text-amber-600 dark:text-amber-400' : 'text-gray-600 dark:text-gray-300'}`}
          >
            {matchSummary(match, includeEmpty)}
          </p>
          {match && !includeEmpty && (
            <details className="text-xs text-gray-600 dark:text-gray-300">
              <summary className="cursor-pointer">Show which titles</summary>
              <ul className="mt-1 space-y-0.5 font-mono">
                {match.matched_titles.map((t) => (
                  <li key={`m-${t}`} className="text-green-700 dark:text-green-400 truncate" title={t}>
                    ✓ {t}
                  </li>
                ))}
                {match.unmatched_titles.map((t) => (
                  <li key={`u-${t}`} className="text-gray-500 dark:text-gray-400 truncate" title={t}>
                    – {t}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Preview shows which of the feed&apos;s current titles the filter selects; YaRSS2 also skips
            items it has already seen.
          </p>
        </section>
      )}

      {pick && (
        <section aria-label="Subscription" className="space-y-2">
          <Field label="Subscription name" note="Defaults to the show title.">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={pickTitle(pick)}
              aria-label="Subscription name"
              className={INPUT}
            />
          </Field>
          <label className="flex items-start gap-2 text-sm text-gray-700 dark:text-gray-200">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              Enable now
              <span className="block text-xs text-gray-500 dark:text-gray-400">
                Active and included the next time you publish. Leave off to save it in Jidou only.
              </span>
            </span>
          </label>
        </section>
      )}

      {error && (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error.message}
        </p>
      )}

      <div className="flex justify-end gap-2">
        {onDone && (
          <Button variant="secondary" tone="light" size="sm" onClick={onDone}>
            Cancel
          </Button>
        )}
        <Button variant="primary" tone="light" size="sm" onClick={submit} disabled={!pick || add.isPending}>
          {add.isPending ? 'Adding…' : 'Add show + subscription'}
        </Button>
      </div>
    </div>
  )
}
