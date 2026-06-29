import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import {
  useRssFeeds,
  useRssSubscriptions,
  usePatchRssSubscription,
  useDeleteRssSubscription,
  useTriggerRssImport,
  useTriggerRssPublish,
  useSuggestRegex,
} from '@/hooks/useRss'
import type { RssFeedRead, RssSubscriptionRead, RssRegexSuggestion, TaskRead } from '@/types/api'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function badge(label: string, color: string) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${color}`}>{label}</span>
  )
}

// ---------------------------------------------------------------------------
// Regex suggest modal
// ---------------------------------------------------------------------------

function RegexSuggestModal({
  sub,
  onClose,
  onApply,
}: {
  sub: RssSubscriptionRead
  onClose: () => void
  onApply?: (include: string, exclude: string) => void
}) {
  const suggest = useSuggestRegex(sub.id)
  const patch = usePatchRssSubscription()
  const [result, setResult] = useState<RssRegexSuggestion | null>(null)

  const handleSuggest = () => {
    suggest.mutate(undefined, { onSuccess: (data) => setResult(data) })
  }

  const handleApply = () => {
    if (!result) return
    if (onApply) {
      onApply(result.regex_include, result.regex_exclude)
      onClose()
    } else {
      patch.mutate(
        { id: sub.id, update: { regex_include: result.regex_include, regex_exclude: result.regex_exclude } },
        { onSuccess: onClose },
      )
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg mx-4">
        <h2 className="text-lg font-semibold mb-1">Suggest regex — {sub.name}</h2>
        <p className="text-sm text-gray-500 mb-4">
          The LLM will suggest include/exclude patterns for a BitTorrent RSS filter.
        </p>

        {result ? (
          <div className="space-y-3 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Include</label>
              <code className="block bg-gray-50 border rounded p-2 text-sm break-all">{result.regex_include}</code>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Exclude</label>
              <code className="block bg-gray-50 border rounded p-2 text-sm break-all">{result.regex_exclude}</code>
            </div>
            <p className="text-xs text-gray-400">Model: {result.model} {result.cached && '(cached)'}</p>
          </div>
        ) : (
          <div className="h-20 flex items-center justify-center text-sm mb-4">
            {suggest.isPending ? (
              <span className="text-gray-400">Asking LLM…</span>
            ) : suggest.isError ? (
              <span className="text-red-500">{(suggest.error as Error)?.message ?? 'Request failed'}</span>
            ) : (
              <span className="text-gray-400">Click "Suggest" to generate patterns.</span>
            )}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50">
            Cancel
          </button>
          {!result && (
            <button
              onClick={handleSuggest}
              disabled={suggest.isPending}
              className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Suggest
            </button>
          )}
          {result && (
            <>
              <button onClick={handleSuggest} disabled={suggest.isPending} className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-50">
                Retry
              </button>
              <button onClick={handleApply} disabled={patch.isPending} className="px-3 py-1.5 text-sm rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50">
                Apply
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subscription edit modal (issue #115)
// ---------------------------------------------------------------------------

interface EditDraft {
  name: string
  feed_id: number | null
  regex_include: string
  regex_exclude: string
  regex_include_ignorecase: boolean
  regex_exclude_ignorecase: boolean
  download_location: string
  move_completed: string
  enabled_in_config: boolean
  label: string
}

function draftFromSub(sub: RssSubscriptionRead): EditDraft {
  return {
    name: sub.name,
    feed_id: sub.feed_id,
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

function SubscriptionEditModal({
  sub,
  feeds,
  onClose,
}: {
  sub: RssSubscriptionRead
  feeds: RssFeedRead[]
  onClose: () => void
}) {
  const [draft, setDraft] = useState<EditDraft>(() => draftFromSub(sub))
  const [showSuggest, setShowSuggest] = useState(false)
  const patch = usePatchRssSubscription()

  const set = <K extends keyof EditDraft>(key: K, value: EditDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleSave = () => {
    patch.mutate(
      {
        id: sub.id,
        update: {
          name: draft.name || undefined,
          feed_id: draft.feed_id,
          regex_include: draft.regex_include || null,
          regex_exclude: draft.regex_exclude || null,
          regex_include_ignorecase: draft.regex_include_ignorecase,
          regex_exclude_ignorecase: draft.regex_exclude_ignorecase,
          download_location: draft.download_location || null,
          move_completed: draft.move_completed || null,
          enabled_in_config: draft.enabled_in_config,
          label: draft.label || null,
        },
      },
      { onSuccess: onClose },
    )
  }

  const field = (label: string, children: React.ReactNode, note?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {note && <p className="text-xs text-gray-400 mt-0.5">{note}</p>}
    </div>
  )

  const textInput = (key: keyof EditDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  const monoInput = (key: keyof EditDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  const checkbox = (key: keyof EditDraft, label: string) => (
    <label className="flex items-center gap-2 text-sm cursor-pointer">
      <input
        type="checkbox"
        checked={draft[key] as boolean}
        onChange={(e) => set(key, e.target.checked)}
        className="rounded"
      />
      {label}
    </label>
  )

  return (
    <>
      {showSuggest && (
        <RegexSuggestModal
          sub={sub}
          onClose={() => setShowSuggest(false)}
          onApply={(inc, exc) => {
            set('regex_include', inc)
            set('regex_exclude', exc)
          }}
        />
      )}
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl flex flex-col max-h-[90vh]">
          {/* Header */}
          <div className="flex items-start justify-between p-5 border-b">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Edit Subscription</h2>
              {sub.show && (
                <Link to={`/shows/${sub.show.id}`} className="text-xs text-indigo-500 hover:underline" onClick={onClose}>
                  {sub.show.title} ↗
                </Link>
              )}
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
          </div>

          {/* Body */}
          <div className="overflow-y-auto p-5 space-y-4">
            {/* Row 1 */}
            <div className="grid grid-cols-2 gap-4">
              {field('Name', textInput('name'))}
              {field('RSS Feed',
                <select
                  value={draft.feed_id ?? ''}
                  onChange={(e) => set('feed_id', e.target.value ? Number(e.target.value) : null)}
                  className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                >
                  <option value="">— None —</option>
                  {feeds.map((f) => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
              )}
            </div>

            {/* Regex */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-600">Regex Patterns</span>
                <button
                  onClick={() => setShowSuggest(true)}
                  className="text-xs text-indigo-500 hover:underline"
                >
                  Suggest via LLM
                </button>
              </div>
              <div className="grid grid-cols-2 gap-4">
                {field('Include', monoInput('regex_include', 'e.g. 1080p|720p'))}
                {field('Exclude', monoInput('regex_exclude', 'e.g. FRENCH|GERMAN'))}
              </div>
              <div className="flex gap-6">
                {checkbox('regex_include_ignorecase', 'Include ignore case')}
                {checkbox('regex_exclude_ignorecase', 'Exclude ignore case')}
              </div>
            </div>

            {/* Paths */}
            <div className="grid grid-cols-2 gap-4">
              {field('Download Location', textInput('download_location', 'Override feed default'), 'Leave blank to use feed default')}
              {field('Move Completed', textInput('move_completed', 'Override feed default'), 'Leave blank to use feed default')}
            </div>

            {/* Label + Enabled */}
            <div className="grid grid-cols-2 gap-4">
              {field('Label', textInput('label', 'e.g. TV'))}
              <div className="flex items-end pb-1">
                {checkbox('enabled_in_config', 'Enabled in config (published to server)')}
              </div>
            </div>

            {/* Read-only info */}
            <div className="grid grid-cols-3 gap-4 pt-2 border-t">
              <div>
                <p className="text-xs font-medium text-gray-500">Remote Key</p>
                <p className="text-sm font-mono">{sub.remote_key ?? <span className="text-yellow-600">new</span>}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500">Active (remote)</p>
                <p className="text-sm">
                  {sub.active
                    ? badge('active', 'bg-green-100 text-green-700')
                    : badge('inactive', 'bg-gray-100 text-gray-500')}
                </p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500">Last Match</p>
                <p className="text-sm text-gray-600">{sub.last_match ?? '—'}</p>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
            <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">
              Cancel
            </button>
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

// ---------------------------------------------------------------------------
// Inline include-regex edit (still used in table)
// ---------------------------------------------------------------------------

function InlineRegexEdit({ sub }: { sub: RssSubscriptionRead }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(sub.regex_include ?? '')
  const patch = usePatchRssSubscription()

  const save = () => {
    patch.mutate(
      { id: sub.id, update: { regex_include: value || null } },
      { onSuccess: () => setEditing(false) },
    )
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setValue(sub.regex_include ?? ''); setEditing(true) }}
        className="text-left text-xs font-mono text-gray-600 hover:text-gray-900 truncate max-w-[200px]"
        title={sub.regex_include ?? 'Click to set'}
      >
        {sub.regex_include ?? <span className="text-gray-300 italic">not set</span>}
      </button>
    )
  }

  return (
    <div className="flex gap-1 items-center">
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') setEditing(false)
        }}
        className="text-xs font-mono border rounded px-1 py-0.5 w-[160px]"
      />
      <button onClick={save} disabled={patch.isPending} className="text-xs text-green-700 hover:underline">Save</button>
      <button onClick={() => setEditing(false)} className="text-xs text-gray-400 hover:underline">✕</button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subscriptions table
// ---------------------------------------------------------------------------

function SubscriptionsTable({
  subs,
  feeds,
}: {
  subs: RssSubscriptionRead[]
  feeds: RssFeedRead[]
}) {
  const patch = usePatchRssSubscription()
  const del = useDeleteRssSubscription()
  const [editSub, setEditSub] = useState<RssSubscriptionRead | null>(null)

  return (
    <>
      {editSub && (
        <SubscriptionEditModal sub={editSub} feeds={feeds} onClose={() => setEditSub(null)} />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2">Key</th>
              <th className="px-3 py-2">Name / Show</th>
              <th className="px-3 py-2">Feed</th>
              <th className="px-3 py-2">Include regex</th>
              <th className="px-3 py-2">Enabled</th>
              <th className="px-3 py-2">Active</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subs.map((sub) => (
              <tr key={sub.id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">
                  {sub.remote_key ?? badge('new', 'bg-yellow-100 text-yellow-700')}
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => setEditSub(sub)}
                    className="font-medium truncate max-w-[160px] text-left hover:text-indigo-600 hover:underline"
                    title="Edit subscription"
                  >
                    {sub.name}
                  </button>
                  {sub.show && (
                    <Link to={`/shows/${sub.show.id}`} className="block text-xs text-indigo-500 hover:underline">
                      {sub.show.title}
                    </Link>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-gray-600">
                  {sub.feed?.name ?? <span className="text-gray-300">—</span>}
                </td>
                <td className="px-3 py-2">
                  <InlineRegexEdit sub={sub} />
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => patch.mutate({ id: sub.id, update: { enabled_in_config: !sub.enabled_in_config } })}
                    className={`w-10 h-5 rounded-full transition-colors ${sub.enabled_in_config ? 'bg-green-500' : 'bg-gray-300'}`}
                    title={sub.enabled_in_config ? 'Disable' : 'Enable'}
                  >
                    <span
                      className={`block w-4 h-4 bg-white rounded-full shadow transform transition-transform mx-0.5 ${sub.enabled_in_config ? 'translate-x-5' : 'translate-x-0'}`}
                    />
                  </button>
                </td>
                <td className="px-3 py-2">
                  {sub.active
                    ? badge('active', 'bg-green-100 text-green-700')
                    : badge('inactive', 'bg-gray-100 text-gray-500')}
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-2 items-center">
                    <button onClick={() => setEditSub(sub)} className="text-xs text-gray-500 hover:underline">
                      Edit
                    </button>
                    {!sub.enabled_in_config && (
                      <button
                        onClick={() => { if (confirm(`Delete subscription "${sub.name}"?`)) del.mutate(sub.id) }}
                        className="text-xs text-red-400 hover:underline"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {subs.length === 0 && (
          <p className="text-center text-gray-400 py-8 text-sm">No subscriptions match the filter.</p>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

export default function RSS() {
  const [nameSearch, setNameSearch] = useState('')
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'stubs'>('all')
  const [feedFilter, setFeedFilter] = useState<number | 'unlinked' | 'all'>('all')
  const [importTaskId, setImportTaskId] = useState<number | null>(null)
  const [publishTaskId, setPublishTaskId] = useState<number | null>(null)
  const qc = useQueryClient()

  const { data: feeds = [] } = useRssFeeds()
  const { data: subs, isLoading } = useRssSubscriptions()
  const triggerImport = useTriggerRssImport()
  const triggerPublish = useTriggerRssPublish()

  const { data: importTask } = useQuery({
    queryKey: ['tasks', importTaskId],
    queryFn: () => api.get<TaskRead>(`/tasks/${importTaskId}`),
    enabled: !!importTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL.has(status) ? false : 3000
    },
  })
  const { data: publishTask } = useQuery({
    queryKey: ['tasks', publishTaskId],
    queryFn: () => api.get<TaskRead>(`/tasks/${publishTaskId}`),
    enabled: !!publishTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL.has(status) ? false : 3000
    },
  })

  useEffect(() => {
    if (importTask?.status === 'completed') {
      qc.invalidateQueries({ queryKey: ['rss', 'feeds'] })
      qc.invalidateQueries({ queryKey: ['rss', 'subscriptions'] })
    }
  }, [importTask?.status, qc])

  useEffect(() => {
    if (publishTask?.status === 'completed') {
      qc.invalidateQueries({ queryKey: ['rss', 'subscriptions'] })
    }
  }, [publishTask?.status, qc])

  const filteredSubs = (subs ?? []).filter((s) => {
    if (nameSearch && !s.name.toLowerCase().includes(nameSearch.toLowerCase())) return false
    if (enabledFilter === 'enabled' && !s.enabled_in_config) return false
    if (enabledFilter === 'stubs' && s.remote_key !== null) return false
    if (feedFilter === 'unlinked' && s.feed_id !== null) return false
    if (typeof feedFilter === 'number' && s.feed_id !== feedFilter) return false
    return true
  })

  function TaskStatusBadge({ task }: { task: TaskRead | undefined }) {
    if (!task) return null
    const colors: Record<string, string> = {
      completed: 'text-green-600',
      failed: 'text-red-500',
      running: 'text-blue-500',
      pending: 'text-yellow-600',
    }
    return (
      <span className={`text-xs font-medium ${colors[task.status] ?? 'text-gray-500'}`}>
        {task.status}{task.progress_message ? ` — ${task.progress_message}` : ''}
      </span>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">RSS</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage YaRSS2 feeds and subscriptions. Import from or publish to the remote config file.
          </p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex gap-2">
            <button
              onClick={() => triggerImport.mutate(undefined, { onSuccess: (t) => setImportTaskId(t.id) })}
              disabled={triggerImport.isPending}
              className="px-4 py-2 text-sm rounded bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {triggerImport.isPending ? 'Dispatching…' : 'Import from server'}
            </button>
            <button
              onClick={() => triggerPublish.mutate(undefined, { onSuccess: (t) => setPublishTaskId(t.id) })}
              disabled={triggerPublish.isPending}
              className="px-4 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {triggerPublish.isPending ? 'Dispatching…' : 'Publish to server'}
            </button>
          </div>
          {importTask && <div className="text-right text-xs">Import: <TaskStatusBadge task={importTask} /></div>}
          {publishTask && <div className="text-right text-xs">Publish: <TaskStatusBadge task={publishTask} /></div>}
          <p className="text-xs text-gray-400">
            Check the <Link to="/tasks" className="text-indigo-500 hover:underline">Tasks page</Link> for details.
          </p>
        </div>
      </div>

      {/* Feeds */}
      <section>
        <h2 className="text-base font-semibold text-gray-700 mb-3">Feeds ({feeds.length})</h2>
        {feeds.length === 0 ? (
          <p className="text-sm text-gray-400">No feeds. Run an import to sync from the server.</p>
        ) : (
          <div className="overflow-x-auto border rounded-lg">
            <table className="w-full text-sm text-left">
              <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
                <tr>
                  <th className="px-3 py-2">Key</th>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">URL</th>
                  <th className="px-3 py-2">Default download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {feeds.map((f) => (
                  <tr key={f.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs text-gray-500">{f.remote_key ?? '—'}</td>
                    <td className="px-3 py-2 font-medium">{f.name}</td>
                    <td className="px-3 py-2 text-xs text-gray-500 max-w-[240px] truncate">
                      <a href={f.url} target="_blank" rel="noreferrer" className="hover:underline">{f.url}</a>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">{f.default_download_location ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Subscriptions */}
      <section>
        <div className="flex flex-col gap-3 mb-3 sm:flex-row sm:items-end sm:justify-between">
          <h2 className="text-base font-semibold text-gray-700">
            Subscriptions ({filteredSubs.length} / {subs?.length ?? 0})
          </h2>

          {/* Filter bar (issue #116) */}
          <div className="flex flex-wrap gap-2 items-end">
            {/* Name search */}
            <input
              type="search"
              value={nameSearch}
              onChange={(e) => setNameSearch(e.target.value)}
              placeholder="Search name…"
              className="border rounded px-2 py-1 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />

            {/* Enabled filter */}
            <select
              value={enabledFilter}
              onChange={(e) => setEnabledFilter(e.target.value as typeof enabledFilter)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="all">All</option>
              <option value="enabled">Enabled only</option>
              <option value="stubs">Stubs only (no remote key)</option>
            </select>

            {/* Feed filter */}
            <select
              value={feedFilter === 'all' ? 'all' : feedFilter === 'unlinked' ? 'unlinked' : String(feedFilter)}
              onChange={(e) => {
                const v = e.target.value
                setFeedFilter(v === 'all' ? 'all' : v === 'unlinked' ? 'unlinked' : Number(v))
              }}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="all">All feeds</option>
              <option value="unlinked">Unlinked</option>
              {feeds.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </div>
        </div>

        {isLoading ? (
          <p className="text-sm text-gray-400">Loading subscriptions…</p>
        ) : (
          <div className="border rounded-lg">
            <SubscriptionsTable subs={filteredSubs} feeds={feeds} />
          </div>
        )}
      </section>
    </div>
  )
}
