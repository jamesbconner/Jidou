import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type {
  RssFeedRead,
  RssFeedCreate,
  RssFeedUpdate,
  RssSubscriptionRead,
  RssSubscriptionCreate,
  RssSubscriptionRecommendation,
  TaskRead,
} from '@/types/api'
import {
  rssKeys,
  useRssFeeds,
  useRssSubscriptions,
  useCreateRssSubscription,
  usePatchRssSubscription,
  useDeleteRssSubscription,
  useCreateRssFeed,
  usePatchRssFeed,
  useDeleteRssFeed,
  useTriggerRssImport,
  useTriggerRssPublish,
  useRssRecommendations,
  useBulkPatchRssSubscriptions,
} from '@/hooks/useRss'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function badge(label: string, color: string) {
  return <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${color}`}>{label}</span>
}

// Reusable modal field row — also used by SubscriptionCreateModal and FeedFormModal below.
function Field({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
      {note && <p className="text-xs text-gray-400 mt-0.5">{note}</p>}
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

// ---------------------------------------------------------------------------
// Subscription create modal
// ---------------------------------------------------------------------------

function SubscriptionCreateModal({ feeds, onClose }: { feeds: RssFeedRead[]; onClose: () => void }) {
  const create = useCreateRssSubscription()
  const [draft, setDraft] = useState<SubDraft>({
    name: '',
    feed_id: null,
    show_id: null,
    active: false,
    regex_include: '',
    regex_exclude: '',
    regex_include_ignorecase: true,
    regex_exclude_ignorecase: true,
    download_location: '',
    move_completed: '',
    enabled_in_config: false,
    label: '',
  })

  const set = <K extends keyof SubDraft>(key: K, value: SubDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleCreate = () => {
    if (!draft.name.trim()) return
    const body: RssSubscriptionCreate = {
      name: draft.name.trim(),
      feed_id: draft.feed_id,
      active: draft.active,
      regex_include: draft.regex_include || null,
      regex_exclude: draft.regex_exclude || null,
      regex_include_ignorecase: draft.regex_include_ignorecase,
      regex_exclude_ignorecase: draft.regex_exclude_ignorecase,
      download_location: draft.download_location || null,
      move_completed: draft.move_completed || null,
      enabled_in_config: draft.enabled_in_config,
      label: draft.label || null,
    }
    create.mutate(body, { onSuccess: onClose })
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
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900">New Subscription</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Name *">{textInput('name', 'e.g. My Show S01')}</Field>
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

          <div className="space-y-3">
            <span className="text-xs font-medium text-gray-600">Regex Patterns</span>
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
            <Field label="Download Location" note="Leave blank to use feed default">{textInput('download_location')}</Field>
            <Field label="Move Completed" note="Leave blank to use feed default">{textInput('move_completed')}</Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Label">{textInput('label', 'e.g. TV')}</Field>
            <div className="flex flex-col gap-2 justify-end pb-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer" title="Included in the published YaRSS2 config.">
                <input type="checkbox" checked={draft.enabled_in_config} onChange={(e) => set('enabled_in_config', e.target.checked)} className="rounded" />
                Enabled in config
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer" title="Jidou controls this flag. Active subscriptions are treated as live by the downloader.">
                <input type="checkbox" checked={draft.active} onChange={(e) => set('active', e.target.checked)} className="rounded" />
                Active
              </label>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
          <button
            onClick={handleCreate}
            disabled={create.isPending || !draft.name.trim()}
            className="px-4 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Compose subscription dict (mirrors _build_sub_dict in publish orchestrator)
// ---------------------------------------------------------------------------

function composeSubDict(sub: RssSubscriptionRead): Record<string, unknown> {
  const dict: Record<string, unknown> = { ...(sub.extra_config ?? {}) }
  dict['name'] = sub.name
  dict['regex_include_ignorecase'] = sub.regex_include_ignorecase
  dict['regex_exclude_ignorecase'] = sub.regex_exclude_ignorecase
  dict['active'] = sub.active
  if (sub.regex_include !== null) dict['regex_include'] = sub.regex_include
  if (sub.regex_exclude !== null) dict['regex_exclude'] = sub.regex_exclude
  if (sub.label !== null) dict['label'] = sub.label
  if (sub.last_match !== null) dict['last_match'] = sub.last_match
  const dlLoc = sub.download_location || sub.feed?.default_download_location || null
  const mvLoc = sub.move_completed || sub.feed?.default_move_completed || null
  if (dlLoc !== null) dict['download_location'] = dlLoc
  if (mvLoc !== null) dict['move_completed'] = mvLoc
  if (sub.feed?.remote_key) {
    dict['rssfeed_key'] = sub.feed.remote_key
  }
  return dict
}

// ---------------------------------------------------------------------------
// Subscription preview modal
// ---------------------------------------------------------------------------

function SubPreviewModal({ sub, onClose }: { sub: RssSubscriptionRead; onClose: () => void }) {
  const composed = composeSubDict(sub)
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-base font-semibold text-gray-900">Subscription Config Preview</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>
        <div className="overflow-y-auto p-4">
          <p className="text-xs text-gray-500 mb-2">
            Composed output for <strong>{sub.name}</strong> (key: {sub.remote_key ?? 'unassigned'})
          </p>
          <pre className="bg-gray-50 border rounded p-3 text-xs font-mono whitespace-pre-wrap break-all">
            {JSON.stringify(composed, null, 2)}
          </pre>
        </div>
        <div className="flex justify-end p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Close</button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Subscriptions table
// ---------------------------------------------------------------------------

function SubscriptionsTable({ subs, feeds }: { subs: RssSubscriptionRead[]; feeds: RssFeedRead[] }) {
  const patch = usePatchRssSubscription()
  const del = useDeleteRssSubscription()
  const [editSub, setEditSub] = useState<RssSubscriptionRead | null>(null)
  const [previewSub, setPreviewSub] = useState<RssSubscriptionRead | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <>
      {createOpen && <SubscriptionCreateModal feeds={feeds} onClose={() => setCreateOpen(false)} />}
      {editSub && <SubscriptionEditModal sub={editSub} feeds={feeds} onClose={() => setEditSub(null)} />}
      {previewSub && <SubPreviewModal sub={previewSub} onClose={() => setPreviewSub(null)} />}

      <div className="flex justify-end mb-2">
        <button
          onClick={() => setCreateOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          + New Subscription
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 w-16">Key</th>
              <th className="px-3 py-2">Name / Show</th>
              <th className="px-3 py-2 w-20" title="Included in the published YaRSS2 config. Stubs are excluded until explicitly enabled.">Enabled</th>
              <th className="px-3 py-2 w-24" title="Jidou controls this flag. Active subscriptions are treated as live by the downloader. Stubs are always inactive.">Active</th>
              <th className="px-3 py-2 w-36"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subs.map((sub) => {
              const isStub = sub.remote_key === null && !sub.enabled_in_config
              return (
                <tr key={sub.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-mono text-xs text-gray-500">
                    {sub.remote_key ?? badge('stub', 'bg-yellow-100 text-yellow-700')}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => setEditSub(sub)}
                      className="font-medium text-left hover:text-indigo-600 hover:underline"
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
                  <td className="px-3 py-2">
                    <button
                      onClick={() => patch.mutate({ id: sub.id, update: { enabled_in_config: !sub.enabled_in_config } })}
                      className={`w-10 h-5 rounded-full transition-colors ${sub.enabled_in_config ? 'bg-green-500' : 'bg-gray-300'}`}
                      title={sub.enabled_in_config
                        ? 'Enabled — included in published config. Click to disable.'
                        : 'Disabled — not included in published config. Click to enable.'}
                      aria-label={sub.enabled_in_config ? 'Enabled in config — click to disable' : 'Disabled from config — click to enable'}
                      aria-pressed={sub.enabled_in_config}
                    >
                      <span className={`block w-4 h-4 bg-white rounded-full shadow transform transition-transform mx-0.5 ${sub.enabled_in_config ? 'translate-x-5' : 'translate-x-0'}`} />
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    {isStub ? (
                      <span
                        title="Stubs are always inactive until promoted to a real subscription."
                        className="cursor-default"
                      >
                        {badge('inactive', 'bg-gray-100 text-gray-400')}
                      </span>
                    ) : (
                      <button
                        onClick={() => patch.mutate({ id: sub.id, update: { active: !sub.active } })}
                        title={sub.active
                          ? 'Active — downloader treats this as live. Click to deactivate.'
                          : 'Inactive — downloader skips this. Click to activate.'}
                        aria-label={sub.active ? 'Active — click to deactivate' : 'Inactive — click to activate'}
                        aria-pressed={sub.active}
                      >
                        {sub.active
                          ? badge('active', 'bg-green-100 text-green-700 hover:ring-1 hover:ring-green-400')
                          : badge('inactive', 'bg-gray-100 text-gray-500 hover:ring-1 hover:ring-gray-400')}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2 items-center">
                      <button onClick={() => setEditSub(sub)} className="text-xs text-gray-500 hover:underline">Edit</button>
                      <button onClick={() => setPreviewSub(sub)} className="text-xs text-gray-500 hover:underline">Preview</button>
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
              )
            })}
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
// Feed form modal (create and edit)
// ---------------------------------------------------------------------------

interface FeedDraft {
  name: string
  url: string
  remote_key: string
  default_download_location: string
  default_move_completed: string
  active: boolean
}

function FeedFormModal({ feed, onClose }: { feed: RssFeedRead | null; onClose: () => void }) {
  const create = useCreateRssFeed()
  const patch = usePatchRssFeed()
  const isEdit = feed !== null

  const [draft, setDraft] = useState<FeedDraft>({
    name: feed?.name ?? '',
    url: feed?.url ?? '',
    remote_key: feed?.remote_key ?? '',
    default_download_location: feed?.default_download_location ?? '',
    default_move_completed: feed?.default_move_completed ?? '',
    active: feed?.active ?? true,
  })

  const set = <K extends keyof FeedDraft>(key: K, value: FeedDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleSave = () => {
    if (!draft.name.trim() || !draft.url.trim()) return
    if (isEdit) {
      const update: RssFeedUpdate = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        remote_key: draft.remote_key.trim() || null,
        default_download_location: draft.default_download_location.trim() || null,
        default_move_completed: draft.default_move_completed.trim() || null,
        active: draft.active,
      }
      patch.mutate({ id: feed.id, update }, { onSuccess: onClose })
    } else {
      const body: RssFeedCreate = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        remote_key: draft.remote_key.trim() || null,
        default_download_location: draft.default_download_location.trim() || null,
        default_move_completed: draft.default_move_completed.trim() || null,
        active: draft.active,
      }
      create.mutate(body, { onSuccess: onClose })
    }
  }

  const isPending = create.isPending || patch.isPending

  const textInput = (key: keyof FeedDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900">{isEdit ? 'Edit Feed' : 'New Feed'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Name *">{textInput('name', 'e.g. ShowRSS')}</Field>
            <Field label="Remote Key" note="YaRSS2 feed key (e.g. 1, 2). Leave blank for manually-only feeds.">{textInput('remote_key', 'e.g. 1')}</Field>
          </div>
          <Field label="URL *">{textInput('url', 'https://…')}</Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Default Download Location" note="Used by subscriptions that don't override it.">{textInput('default_download_location')}</Field>
            <Field label="Default Move Completed" note="Used by subscriptions that don't override it.">{textInput('default_move_completed')}</Field>
          </div>
          <label
            className="flex items-center gap-2 text-sm cursor-pointer"
            title="Inactive feeds are excluded from the published YaRSS2 config."
          >
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(e) => set('active', e.target.checked)}
              className="rounded"
            />
            Active (included in published config)
          </label>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
          <button
            onClick={handleSave}
            disabled={isPending || !draft.name.trim() || !draft.url.trim()}
            className="px-4 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {isPending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Feeds table
// ---------------------------------------------------------------------------

function FeedsTable({ feeds }: { feeds: RssFeedRead[] }) {
  const patch = usePatchRssFeed()
  const del = useDeleteRssFeed()
  const [editFeed, setEditFeed] = useState<RssFeedRead | null>(null)
  const [createOpen, setCreateOpen] = useState(false)

  return (
    <>
      {createOpen && <FeedFormModal feed={null} onClose={() => setCreateOpen(false)} />}
      {editFeed && <FeedFormModal feed={editFeed} onClose={() => setEditFeed(null)} />}

      <div className="flex justify-end mb-2">
        <button
          onClick={() => setCreateOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700"
        >
          + New Feed
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2 w-12">Key</th>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2 max-w-[200px]">URL</th>
              <th className="px-3 py-2">Default Download</th>
              <th className="px-3 py-2">Default Move</th>
              <th className="px-3 py-2 w-24" title="Inactive feeds are excluded from the published YaRSS2 config.">Active</th>
              <th className="px-3 py-2 w-24"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {feeds.map((f) => (
              <tr key={f.id} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{f.remote_key ?? '—'}</td>
                <td className="px-3 py-2 font-medium">
                  <button onClick={() => setEditFeed(f)} className="hover:text-indigo-600 hover:underline text-left">
                    {f.name}
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500 max-w-[200px] truncate">
                  <a href={f.url} target="_blank" rel="noreferrer" className="hover:underline" title={f.url}>{f.url}</a>
                </td>
                <td className="px-3 py-2 text-xs text-gray-500">{f.default_download_location ?? '—'}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{f.default_move_completed ?? '—'}</td>
                <td className="px-3 py-2">
                  <button
                    onClick={() => patch.mutate({ id: f.id, update: { active: !f.active } })}
                    title={f.active
                      ? 'Active — included in published config. Click to deactivate.'
                      : 'Inactive — excluded from published config. Click to activate.'}
                    aria-label={f.active ? 'Feed active — click to deactivate' : 'Feed inactive — click to activate'}
                    aria-pressed={f.active}
                  >
                    {f.active
                      ? badge('active', 'bg-green-100 text-green-700 hover:ring-1 hover:ring-green-400')
                      : badge('inactive', 'bg-gray-100 text-gray-500 hover:ring-1 hover:ring-gray-400')}
                  </button>
                </td>
                <td className="px-3 py-2">
                  <div className="flex gap-2">
                    <button onClick={() => setEditFeed(f)} className="text-xs text-gray-500 hover:underline">Edit</button>
                    <button
                      onClick={() => { if (confirm(`Delete feed "${f.name}"?`)) del.mutate(f.id) }}
                      className="text-xs text-red-400 hover:underline"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {feeds.length === 0 && (
          <p className="text-center text-gray-400 py-8 text-sm">No feeds. Run an import or create one manually.</p>
        )}
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Recommendations tab
// ---------------------------------------------------------------------------

function RecommendationsTab() {
  const { data: recs = [], isLoading, refetch } = useRssRecommendations()
  const patch = usePatchRssSubscription()
  const bulkPatch = useBulkPatchRssSubscriptions()
  const [filter, setFilter] = useState<'all' | 'activate' | 'deactivate'>('all')
  const qc = useQueryClient()

  const visible = recs.filter((r) => filter === 'all' || r.recommendation === filter)
  const deactivateCount = recs.filter((r) => r.recommendation === 'deactivate').length
  const activateCount = recs.filter((r) => r.recommendation === 'activate').length

  const handleAcceptAll = () => {
    const items = visible.map((r) => ({ id: r.id, active: r.recommendation === 'activate' }))
    bulkPatch.mutate(items)
  }

  const handleAcceptOne = (rec: RssSubscriptionRecommendation) => {
    patch.mutate(
      { id: rec.id, update: { active: rec.recommendation === 'activate' } },
      { onSuccess: () => qc.invalidateQueries({ queryKey: rssKeys.recommendations() }) },
    )
  }

  if (isLoading) return <p className="text-sm text-gray-400 py-6">Loading recommendations…</p>

  return (
    <section className="space-y-4">
      {/* Summary + controls */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-2">
          {(['all', 'deactivate', 'activate'] as const).map((f) => {
            const label =
              f === 'all'
                ? `All (${recs.length})`
                : f === 'deactivate'
                ? `Deactivate (${deactivateCount})`
                : `Activate (${activateCount})`
            return (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1 text-xs rounded-full border font-medium transition-colors ${
                  filter === f
                    ? f === 'deactivate'
                      ? 'bg-amber-100 border-amber-400 text-amber-800'
                      : f === 'activate'
                      ? 'bg-green-100 border-green-400 text-green-800'
                      : 'bg-indigo-100 border-indigo-400 text-indigo-800'
                    : 'border-gray-300 text-gray-500 hover:border-gray-400'
                }`}
              >
                {label}
              </button>
            )
          })}
        </div>
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => refetch()}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100"
          >
            Refresh
          </button>
          <button
            onClick={handleAcceptAll}
            disabled={visible.length === 0 || bulkPatch.isPending}
            className="px-3 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {bulkPatch.isPending ? 'Applying…' : `Accept all (${visible.length})`}
          </button>
        </div>
      </div>

      {recs.length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-gray-400 text-sm">
          No recommendations — all subscriptions match their show&apos;s current status.
        </div>
      ) : visible.length === 0 ? (
        <div className="border rounded-lg p-8 text-center text-gray-400 text-sm">
          No subscriptions match the current filter.
        </div>
      ) : (
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
              <tr>
                <th className="px-3 py-2">Subscription / Show</th>
                <th className="px-3 py-2 w-32">TMDB Status</th>
                <th className="px-3 py-2 w-24">Currently</th>
                <th className="px-3 py-2 w-32">Recommendation</th>
                <th className="px-3 py-2 w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visible.map((rec) => (
                <tr key={rec.id} className="hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <p className="font-medium">{rec.name}</p>
                    {rec.show && (
                      <Link
                        to={`/shows/${rec.show.id}`}
                        className="text-xs text-indigo-500 hover:underline"
                      >
                        {rec.show.title} ↗
                      </Link>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-600">
                    {rec.show?.status ?? '—'}
                  </td>
                  <td className="px-3 py-2">
                    {rec.active
                      ? badge('active', 'bg-green-100 text-green-700')
                      : badge('inactive', 'bg-gray-100 text-gray-500')}
                  </td>
                  <td className="px-3 py-2">
                    {rec.recommendation === 'deactivate'
                      ? badge('Deactivate', 'bg-amber-100 text-amber-700')
                      : badge('Activate', 'bg-green-100 text-green-700')}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => handleAcceptOne(rec)}
                      disabled={patch.isPending || bulkPatch.isPending}
                      className="text-xs text-indigo-600 hover:underline disabled:opacity-50"
                    >
                      Accept
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

export default function RSS() {
  const [tab, setTab] = useState<'subscriptions' | 'feeds' | 'recommendations'>('subscriptions')
  const [nameSearch, setNameSearch] = useState('')
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [feedFilter, setFeedFilter] = useState<number | 'unlinked' | 'all'>('all')
  const [importTaskId, setImportTaskId] = useState<number | null>(null)
  const [publishTaskId, setPublishTaskId] = useState<number | null>(null)
  const [downloading, setDownloading] = useState(false)
  const qc = useQueryClient()

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const resp = await fetch('/api/rss/download')
      if (!resp.ok) throw new Error(`Server returned ${resp.status}`)
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'yarss2.conf'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(`Download failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setDownloading(false)
    }
  }

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
    if (enabledFilter === 'disabled' && s.enabled_in_config) return false
    if (activeFilter === 'active' && !s.active) return false
    if (activeFilter === 'inactive' && s.active) return false
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">RSS</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage YaRSS2 feeds and subscriptions. Import from or publish to the remote config file.
          </p>
        </div>
        <div className="flex flex-col gap-2 items-end">
          <div className="flex gap-2 items-center">
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
            <div className="w-px h-6 bg-gray-300 mx-1" />
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="px-4 py-2 text-sm rounded bg-gray-200 text-gray-700 hover:bg-gray-300 disabled:opacity-50"
            >
              {downloading ? 'Downloading…' : 'Download'}
            </button>
          </div>
          {importTask && <div className="text-right text-xs">Import: <TaskStatusBadge task={importTask} /></div>}
          {publishTask && <div className="text-right text-xs">Publish: <TaskStatusBadge task={publishTask} /></div>}
          <p className="text-xs text-gray-400">
            Check the <Link to="/tasks" className="text-indigo-500 hover:underline">Tasks page</Link> for details.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {(['subscriptions', 'feeds', 'recommendations'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`pb-3 text-sm font-medium capitalize border-b-2 transition-colors ${
                tab === t
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {t === 'subscriptions'
                ? `Subscriptions (${subs?.length ?? 0})`
                : t === 'feeds'
                ? `Feeds (${feeds.length})`
                : 'Recommendations'}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {tab === 'subscriptions' && (
        <section>
          <div className="flex flex-wrap gap-2 items-center mb-3">
            <input
              type="search"
              value={nameSearch}
              onChange={(e) => setNameSearch(e.target.value)}
              placeholder="Search name…"
              className="border rounded px-2 py-1 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <select
              value={enabledFilter}
              onChange={(e) => setEnabledFilter(e.target.value as typeof enabledFilter)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="all">Any enabled</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
            <select
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value as typeof activeFilter)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="all">Any active</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
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
              {feeds.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <span className="text-xs text-gray-400 ml-1">{filteredSubs.length} / {subs?.length ?? 0}</span>
          </div>

          {isLoading ? (
            <p className="text-sm text-gray-400">Loading subscriptions…</p>
          ) : (
            <div className="border rounded-lg p-3">
              <SubscriptionsTable subs={filteredSubs} feeds={feeds} />
            </div>
          )}
        </section>
      )}

      {tab === 'feeds' && (
        <section>
          <div className="border rounded-lg p-3">
            <FeedsTable feeds={feeds} />
          </div>
        </section>
      )}

      {tab === 'recommendations' && <RecommendationsTab />}
    </div>
  )
}
