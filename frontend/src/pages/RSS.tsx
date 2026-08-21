import { useState, useEffect } from 'react'
import { Link } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TaskRead } from '@/types/api'
import {
  useRssFeeds,
  useRssSubscriptions,
  useTriggerRssImport,
  useTriggerRssPublish,
  useRssDownload,
} from '@/hooks/useRss'
import { SubscriptionsTable } from '@/components/SubscriptionsTable'
import { FeedsTable } from '@/components/FeedsTable'
import { RecommendationsTab } from '@/components/RecommendationsTab'

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

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

export default function RSS() {
  const [tab, setTab] = useState<'subscriptions' | 'feeds' | 'recommendations'>('subscriptions')
  const [nameSearch, setNameSearch] = useState('')
  const [enabledFilter, setEnabledFilter] = useState<'all' | 'enabled' | 'disabled'>('all')
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [feedFilter, setFeedFilter] = useState<number | 'unlinked' | 'all'>('all')
  const [importTaskId, setImportTaskId] = useState<number | null>(null)
  const [publishTaskId, setPublishTaskId] = useState<number | null>(null)
  const qc = useQueryClient()

  const { data: feeds = [] } = useRssFeeds()
  const { data: subs, isLoading } = useRssSubscriptions()
  const triggerImport = useTriggerRssImport()
  const triggerPublish = useTriggerRssPublish()
  const download = useRssDownload()

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">RSS</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
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
            <div className="w-px h-6 bg-gray-300 dark:bg-gray-700 mx-1" />
            <button
              onClick={() => download.mutate()}
              disabled={download.isPending}
              className="px-4 py-2 text-sm rounded bg-gray-200 text-gray-700 hover:bg-gray-300 disabled:opacity-50 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              {download.isPending ? 'Downloading…' : 'Download'}
            </button>
          </div>
          {importTask && <div className="text-right text-xs dark:text-gray-300">Import: <TaskStatusBadge task={importTask} /></div>}
          {publishTask && <div className="text-right text-xs dark:text-gray-300">Publish: <TaskStatusBadge task={publishTask} /></div>}
          {triggerImport.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Import failed to start: {(triggerImport.error as Error)?.message ?? 'Unknown error'}
            </p>
          )}
          {triggerPublish.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Publish failed to start: {(triggerPublish.error as Error)?.message ?? 'Unknown error'}
            </p>
          )}
          {download.isError && (
            <p className="text-xs text-red-600 dark:text-red-400">
              Download failed: {(download.error as Error)?.message ?? 'Unknown error'}
            </p>
          )}
          <p className="text-xs text-gray-400 dark:text-gray-500">
            Check the <Link to="/tasks" className="text-indigo-500 dark:text-indigo-400 hover:underline">Tasks page</Link> for details.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-800">
        <nav className="-mb-px flex gap-6">
          {(['subscriptions', 'feeds', 'recommendations'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`pb-3 text-sm font-medium capitalize border-b-2 transition-colors ${
                tab === t
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-500 dark:hover:text-gray-300 dark:hover:border-gray-700'
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
              className="border rounded px-2 py-1 text-sm w-44 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-800 dark:text-gray-100"
            />
            <select
              value={enabledFilter}
              onChange={(e) => setEnabledFilter(e.target.value as typeof enabledFilter)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="all">Any enabled</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
            <select
              value={activeFilter}
              onChange={(e) => setActiveFilter(e.target.value as typeof activeFilter)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-800 dark:text-gray-100"
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
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-800 dark:text-gray-100"
            >
              <option value="all">All feeds</option>
              <option value="unlinked">Unlinked</option>
              {feeds.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            <span className="text-xs text-gray-400 dark:text-gray-500 ml-1">{filteredSubs.length} / {subs?.length ?? 0}</span>
          </div>

          {isLoading ? (
            <p className="text-sm text-gray-400 dark:text-gray-500">Loading subscriptions…</p>
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
