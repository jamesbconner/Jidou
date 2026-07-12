import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import type { RssFeedRead, RssSubscriptionRead, RssSubscriptionUpdate } from '@/types/api'
import { usePatchRssSubscription, useSuggestRegex } from '@/hooks/useRss'
import { useShows } from '@/hooks/useShows'

// Reusable modal field row
function Field({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {note && <p className="text-xs text-gray-400 mt-0.5">{note}</p>}
    </div>
  )
}

function RegexSuggestModal({
  sub,
  onClose,
  onApply,
}: {
  sub: RssSubscriptionRead
  onClose: () => void
  onApply: (inc: string, exc: string) => void
}) {
  const suggest = useSuggestRegex(sub.id)
  const [result, setResult] = useState<{ regex_include: string; regex_exclude: string } | null>(null)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-base font-semibold">Suggest Regex via LLM</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-sm text-gray-600">
            Generate regex patterns for <strong>{sub.name}</strong> using an LLM.
          </p>
          {suggest.isError && (
            <p className="text-sm text-red-600">
              {suggest.error instanceof Error ? suggest.error.message : 'Suggestion failed. Check LLM configuration.'}
            </p>
          )}
          {result ? (
            <div className="space-y-2">
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Include</p>
                <code className="block bg-gray-50 border rounded px-2 py-1.5 text-xs font-mono break-all">{result.regex_include || '(empty)'}</code>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Exclude</p>
                <code className="block bg-gray-50 border rounded px-2 py-1.5 text-xs font-mono break-all">{result.regex_exclude || '(empty)'}</code>
              </div>
            </div>
          ) : (
            !suggest.isError && <p className="text-sm text-gray-400 italic">Click Suggest to generate patterns.</p>
          )}
        </div>
        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
          {result && (
            <button
              onClick={() => { onApply(result.regex_include, result.regex_exclude); onClose() }}
              className="px-3 py-1.5 text-sm rounded bg-green-600 text-white hover:bg-green-700"
            >
              Apply
            </button>
          )}
          <button
            onClick={() => suggest.mutate(undefined, { onSuccess: (r) => setResult(r) })}
            disabled={suggest.isPending}
            className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {suggest.isPending ? 'Generating…' : result ? 'Re-suggest' : 'Suggest'}
          </button>
        </div>
      </div>
    </div>
  )
}

interface SubDraft {
  name: string
  feed_id: number | null
  show_id: number | null
  active: boolean
  regex_include: string
  regex_exclude: string
  regex_include_ignorecase: boolean
  regex_exclude_ignorecase: boolean
  download_location: string
  move_completed: string
  enabled_in_config: boolean
  label: string
}

function draftFromSub(sub: RssSubscriptionRead): SubDraft {
  return {
    name: sub.name,
    feed_id: sub.feed_id,
    show_id: sub.show_id,
    active: sub.active,
    regex_include: sub.regex_include ?? '',
    regex_exclude: sub.regex_exclude ?? '',
    regex_include_ignorecase: sub.regex_include_ignorecase,
    regex_exclude_ignorecase: sub.regex_exclude_ignorecase,
    download_location: sub.download_location ?? '',
    move_completed: sub.move_completed ?? '',
    enabled_in_config: sub.enabled_in_config,
    label: sub.label ?? '',
  }
}

export function SubscriptionEditModal({
  sub,
  feeds,
  onClose,
}: {
  sub: RssSubscriptionRead
  feeds: RssFeedRead[]
  onClose: () => void
}) {
  const [draft, setDraft] = useState<SubDraft>(() => draftFromSub(sub))
  const [showSuggest, setShowSuggest] = useState(false)
  const [showSearch, setShowSearch] = useState('')
  const [showPickerOpen, setShowPickerOpen] = useState(false)
  const showPickerRef = useRef<HTMLDivElement>(null)
  const patch = usePatchRssSubscription()
  // Matches Shows.tsx/Watchlist.tsx's limit override — the default (500) can
  // silently exclude titles sorting past it once the library grows past that
  // size, making this search miss shows that do exist.
  const { data: allShows = [] } = useShows('title_asc', 10000)
  const isStub = sub.remote_key === null && !sub.enabled_in_config

  const linkedShowFromList = allShows.find((s) => s.id === draft.show_id) ?? null
  const linkedShow = draft.show_id !== null
    ? (linkedShowFromList ?? (draft.show_id === sub.show_id ? sub.show : null))
    : null
  const showSearchResults = showSearch.trim().length >= 1
    ? allShows.filter((s) => s.title.toLowerCase().includes(showSearch.toLowerCase())).slice(0, 10)
    : []

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (showPickerRef.current && !showPickerRef.current.contains(e.target as Node)) {
        setShowPickerOpen(false)
      }
    }
    if (showPickerOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showPickerOpen])

  const set = <K extends keyof SubDraft>(key: K, value: SubDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleSave = () => {
    const update: RssSubscriptionUpdate = {
      name: draft.name || undefined,
      feed_id: draft.feed_id,
      show_id: draft.show_id,
      active: isStub ? false : draft.active,
      regex_include: draft.regex_include || null,
      regex_exclude: draft.regex_exclude || null,
      regex_include_ignorecase: draft.regex_include_ignorecase,
      regex_exclude_ignorecase: draft.regex_exclude_ignorecase,
      download_location: draft.download_location || null,
      move_completed: draft.move_completed || null,
      enabled_in_config: draft.enabled_in_config,
      label: draft.label || null,
    }
    patch.mutate({ id: sub.id, update }, { onSuccess: onClose })
  }

  const textInput = (key: keyof SubDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  const monoInput = (key: keyof SubDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  return (
    <>
      {showSuggest && (
        <RegexSuggestModal
          sub={sub}
          onClose={() => setShowSuggest(false)}
          onApply={(inc, exc) => { set('regex_include', inc); set('regex_exclude', exc) }}
        />
      )}
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl flex flex-col max-h-[90vh]">
          <div className="flex items-start justify-between p-5 border-b">
            <h2 className="text-lg font-semibold text-gray-900">Edit Subscription</h2>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
          </div>

          <div className="overflow-y-auto p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Name">{textInput('name')}</Field>
              <Field label="RSS Feed">
                <select
                  value={draft.feed_id ?? ''}
                  onChange={(e) => set('feed_id', e.target.value ? Number(e.target.value) : null)}
                  className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                >
                  <option value="">— None —</option>
                  {feeds.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </Field>
            </div>

            <Field label="Linked Show">
              <div ref={showPickerRef} className="relative">
                {linkedShow ? (
                  <div className="flex items-center gap-2">
                    <Link
                      to={`/shows/${linkedShow.id}`}
                      className="text-sm text-indigo-600 hover:underline"
                      onClick={onClose}
                    >
                      {linkedShow.title} ↗
                    </Link>
                    <button
                      type="button"
                      onClick={() => { set('show_id', null); setShowSearch(''); setShowPickerOpen(false) }}
                      className="text-xs text-red-500 hover:text-red-700"
                    >
                      Remove link
                    </button>
                  </div>
                ) : (
                  <input
                    type="text"
                    value={showSearch}
                    onChange={(e) => { setShowSearch(e.target.value); setShowPickerOpen(true) }}
                    onFocus={() => setShowPickerOpen(true)}
                    placeholder="Search library shows…"
                    className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  />
                )}
                {showPickerOpen && showSearchResults.length > 0 && (
                  <ul className="absolute z-10 mt-1 w-full bg-white border rounded shadow-lg max-h-48 overflow-y-auto text-sm">
                    {showSearchResults.map((s) => (
                      <li key={s.id}>
                        <button
                          type="button"
                          className="w-full text-left px-3 py-1.5 hover:bg-indigo-50"
                          onClick={() => {
                            set('show_id', s.id)
                            setShowSearch('')
                            setShowPickerOpen(false)
                          }}
                        >
                          {s.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Field>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-600">Regex Patterns</span>
                <button onClick={() => setShowSuggest(true)} className="text-xs text-indigo-500 hover:underline">
                  Suggest via LLM
                </button>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Include</label>
                {monoInput('regex_include', 'e.g. 1080p|720p')}
                <label className="flex items-center gap-2 text-xs text-gray-500 mt-1 cursor-pointer">
                  <input type="checkbox" checked={draft.regex_include_ignorecase} onChange={(e) => set('regex_include_ignorecase', e.target.checked)} className="rounded" />
                  Case-insensitive
                </label>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Exclude</label>
                {monoInput('regex_exclude', 'e.g. FRENCH|GERMAN')}
                <label className="flex items-center gap-2 text-xs text-gray-500 mt-1 cursor-pointer">
                  <input type="checkbox" checked={draft.regex_exclude_ignorecase} onChange={(e) => set('regex_exclude_ignorecase', e.target.checked)} className="rounded" />
                  Case-insensitive
                </label>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Download Location" note="Leave blank to use feed default">{textInput('download_location', 'Override feed default')}</Field>
              <Field label="Move Completed" note="Leave blank to use feed default">{textInput('move_completed', 'Override feed default')}</Field>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <Field label="Label">{textInput('label', 'e.g. TV')}</Field>
              <div className="flex flex-col gap-2 justify-end pb-1">
                <label
                  className="flex items-center gap-2 text-sm cursor-pointer"
                  title="Included in the published YaRSS2 config. Stubs are excluded until explicitly enabled."
                >
                  <input type="checkbox" checked={draft.enabled_in_config} onChange={(e) => set('enabled_in_config', e.target.checked)} className="rounded" />
                  Enabled in config
                </label>
                <label
                  className={`flex items-center gap-2 text-sm ${isStub ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                  title={isStub ? 'Stubs are always inactive until promoted to a real subscription.' : 'Jidou controls this flag. Active subscriptions are treated as live by the downloader.'}
                >
                  <input
                    type="checkbox"
                    checked={draft.active}
                    onChange={(e) => set('active', e.target.checked)}
                    disabled={isStub}
                    className="rounded"
                  />
                  Active
                </label>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 mb-1">Remote Key</p>
                <p className="text-sm font-mono">{sub.remote_key ?? <span className="text-yellow-600">new (stub)</span>}</p>
                <p className="text-xs font-medium text-gray-500 mt-2 mb-1">Last Match</p>
                <p className="text-sm text-gray-600">{sub.last_match ?? '—'}</p>
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
            <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
            <button
              onClick={handleSave}
              disabled={patch.isPending}
              className="px-4 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {patch.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
