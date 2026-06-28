import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
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
import type { RssSubscriptionRead, RssRegexSuggestion, TaskRead } from '@/types/api'

type SubFilter = 'all' | 'stubs' | 'enabled' | 'unlinked'

function badge(label: string, color: string) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${color}`}>{label}</span>
  )
}

function RegexSuggestModal({
  sub,
  onClose,
}: {
  sub: RssSubscriptionRead
  onClose: () => void
}) {
  const suggest = useSuggestRegex(sub.id)
  const patch = usePatchRssSubscription()
  const [result, setResult] = useState<RssRegexSuggestion | null>(null)

  const handleSuggest = () => {
    suggest.mutate(undefined, {
      onSuccess: (data) => setResult(data),
    })
  }

  const handleApply = () => {
    if (!result) return
    patch.mutate(
      {
        id: sub.id,
        update: {
          regex_include: result.regex_include,
          regex_exclude: result.regex_exclude,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg mx-4">
        <h2 className="text-lg font-semibold mb-1">Suggest regex — {sub.name}</h2>
        <p className="text-sm text-gray-500 mb-4">
          The LLM will suggest include/exclude patterns for a BitTorrent RSS filter.
        </p>

        {result ? (
          <div className="space-y-3 mb-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Include</label>
              <code className="block bg-gray-50 border rounded p-2 text-sm break-all">
                {result.regex_include}
              </code>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Exclude</label>
              <code className="block bg-gray-50 border rounded p-2 text-sm break-all">
                {result.regex_exclude}
              </code>
            </div>
            <p className="text-xs text-gray-400">
              Model: {result.model} {result.cached && '(cached)'}
            </p>
          </div>
        ) : (
          <div className="h-20 flex items-center justify-center text-gray-400 text-sm mb-4">
            {suggest.isPending ? 'Asking LLM…' : 'Click "Suggest" to generate patterns.'}
            {suggest.isError && (
              <span className="text-red-500">
                {(suggest.error as Error)?.message ?? 'Request failed'}
              </span>
            )}
          </div>
        )}

        <div className="flex gap-2 justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50"
          >
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
              <button
                onClick={handleSuggest}
                disabled={suggest.isPending}
                className="px-3 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
              >
                Retry
              </button>
              <button
                onClick={handleApply}
                disabled={patch.isPending}
                className="px-3 py-1.5 text-sm rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50"
              >
                Apply
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function InlineRegexEdit({
  sub,
  field,
}: {
  sub: RssSubscriptionRead
  field: 'regex_include' | 'regex_exclude'
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(sub[field] ?? '')
  const patch = usePatchRssSubscription()

  const save = () => {
    patch.mutate(
      { id: sub.id, update: { [field]: value || null } },
      { onSuccess: () => setEditing(false) },
    )
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setValue(sub[field] ?? ''); setEditing(true) }}
        className="text-left text-xs font-mono text-gray-600 hover:text-gray-900 truncate max-w-[180px]"
        title={sub[field] ?? 'Click to set'}
      >
        {sub[field] ?? <span className="text-gray-300 italic">not set</span>}
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
      <button onClick={save} disabled={patch.isPending} className="text-xs text-green-700 hover:underline">
        Save
      </button>
      <button onClick={() => setEditing(false)} className="text-xs text-gray-400 hover:underline">
        ✕
      </button>
    </div>
  )
}

function SubscriptionsTable({ subs }: { subs: RssSubscriptionRead[] }) {
  const patch = usePatchRssSubscription()
  const del = useDeleteRssSubscription()
  const [suggestSub, setSuggestSub] = useState<RssSubscriptionRead | null>(null)

  return (
    <>
      {suggestSub && (
        <RegexSuggestModal sub={suggestSub} onClose={() => setSuggestSub(null)} />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase">
            <tr>
              <th className="px-3 py-2">Key</th>
              <th className="px-3 py-2">Name / Show</th>
              <th className="px-3 py-2">Include regex</th>
              <th className="px-3 py-2">Exclude regex</th>
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
                  <div className="font-medium truncate max-w-[160px]">{sub.name}</div>
                  {sub.show && (
                    <Link
                      to={`/shows/${sub.show.id}`}
                      className="text-xs text-indigo-500 hover:underline"
                    >
                      {sub.show.title}
                    </Link>
                  )}
                </td>
                <td className="px-3 py-2">
                  <InlineRegexEdit sub={sub} field="regex_include" />
                </td>
                <td className="px-3 py-2">
                  <InlineRegexEdit sub={sub} field="regex_exclude" />
                </td>
                <td className="px-3 py-2">
                  <button
                    onClick={() =>
                      patch.mutate({
                        id: sub.id,
                        update: { enabled_in_config: !sub.enabled_in_config },
                      })
                    }
                    className={`w-10 h-5 rounded-full transition-colors ${
                      sub.enabled_in_config ? 'bg-green-500' : 'bg-gray-300'
                    }`}
                    title={sub.enabled_in_config ? 'Disable' : 'Enable'}
                  >
                    <span
                      className={`block w-4 h-4 bg-white rounded-full shadow transform transition-transform mx-0.5 ${
                        sub.enabled_in_config ? 'translate-x-5' : 'translate-x-0'
                      }`}
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
                    <button
                      onClick={() => setSuggestSub(sub)}
                      className="text-xs text-indigo-500 hover:underline"
                      title="Suggest regex via LLM"
                    >
                      Suggest
                    </button>
                    {!sub.enabled_in_config && (
                      <button
                        onClick={() => {
                          if (confirm(`Delete subscription "${sub.name}"?`)) del.mutate(sub.id)
                        }}
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

export default function RSS() {
  const [filter, setFilter] = useState<SubFilter>('all')
  const [importTaskId, setImportTaskId] = useState<string | null>(null)
  const [publishTaskId, setPublishTaskId] = useState<string | null>(null)

  const { data: feeds } = useRssFeeds()
  const { data: subs, isLoading } = useRssSubscriptions()
  const triggerImport = useTriggerRssImport()
  const triggerPublish = useTriggerRssPublish()

  // Poll dispatched tasks for completion
  const { data: importTask } = useQuery({
    queryKey: ['tasks', importTaskId],
    queryFn: () => api.get<TaskRead>(`/tasks/${importTaskId}`),
    enabled: !!importTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'pending' ? 3000 : false
    },
  })
  const { data: publishTask } = useQuery({
    queryKey: ['tasks', publishTaskId],
    queryFn: () => api.get<TaskRead>(`/tasks/${publishTaskId}`),
    enabled: !!publishTaskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'running' || status === 'pending' ? 3000 : false
    },
  })

  const filteredSubs = (subs ?? []).filter((s) => {
    if (filter === 'stubs') return s.remote_key === null
    if (filter === 'enabled') return s.enabled_in_config
    if (filter === 'unlinked') return s.show_id === null
    return true
  })

  const handleImport = () => {
    triggerImport.mutate(undefined, {
      onSuccess: (task) => setImportTaskId(task.celery_task_id),
    })
  }

  const handlePublish = () => {
    triggerPublish.mutate(undefined, {
      onSuccess: (task) => setPublishTaskId(task.celery_task_id),
    })
  }

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
        {task.status}
        {task.progress_message ? ` — ${task.progress_message}` : ''}
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
              onClick={handleImport}
              disabled={triggerImport.isPending}
              className="px-4 py-2 text-sm rounded bg-gray-800 text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {triggerImport.isPending ? 'Dispatching…' : 'Import from server'}
            </button>
            <button
              onClick={handlePublish}
              disabled={triggerPublish.isPending}
              className="px-4 py-2 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {triggerPublish.isPending ? 'Dispatching…' : 'Publish to server'}
            </button>
          </div>
          {importTask && (
            <div className="text-right">
              Import: <TaskStatusBadge task={importTask} />
            </div>
          )}
          {publishTask && (
            <div className="text-right">
              Publish: <TaskStatusBadge task={publishTask} />
            </div>
          )}
          <p className="text-xs text-gray-400">
            Check the <Link to="/tasks" className="text-indigo-500 hover:underline">Tasks page</Link> for progress details.
          </p>
        </div>
      </div>

      {/* Feeds */}
      <section>
        <h2 className="text-base font-semibold text-gray-700 mb-3">
          Feeds ({feeds?.length ?? 0})
        </h2>
        {(feeds ?? []).length === 0 ? (
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
                {(feeds ?? []).map((f) => (
                  <tr key={f.id} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-xs text-gray-500">
                      {f.remote_key ?? '—'}
                    </td>
                    <td className="px-3 py-2 font-medium">{f.name}</td>
                    <td className="px-3 py-2 text-xs text-gray-500 max-w-[240px] truncate">
                      <a href={f.url} target="_blank" rel="noreferrer" className="hover:underline">
                        {f.url}
                      </a>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {f.default_download_location ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Subscriptions */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-gray-700">
            Subscriptions ({filteredSubs.length} / {subs?.length ?? 0})
          </h2>
          <div className="flex gap-1">
            {(['all', 'stubs', 'enabled', 'unlinked'] as SubFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`text-xs px-2 py-1 rounded ${
                  filter === f
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <p className="text-sm text-gray-400">Loading subscriptions…</p>
        ) : (
          <div className="border rounded-lg">
            <SubscriptionsTable subs={filteredSubs} />
          </div>
        )}
      </section>
    </div>
  )
}
