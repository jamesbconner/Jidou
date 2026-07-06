import { useState, useEffect } from 'react'
import { useTasks, useTaskCount, useActiveTasks, useTask, useTaskDetail, useTaskDetailCache, useTriggerTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import { TaskEventLog } from '@/components/TaskEventLog'
import type { TaskList, TaskType } from '@/types/api'

function LiveTask({ taskId }: { taskId: number }) {
  const { data: task } = useTask(taskId)
  useTaskProgress(task?.celery_task_id ?? null)
  return null
}

function TaskLogPanel({ task }: { task: TaskList }) {
  const [open, setOpen] = useState(false)
  // useTaskDetail fetches on open and merges the response with any live WS
  // events already in the cache, preventing stale HTTP responses from
  // overwriting events that arrived during the network round-trip.
  const { data: detail } = useTaskDetail(open ? task.id : 0)
  // Subscribe to the cache without fetching so the count badge stays accurate
  // while the panel is closed (populated by LiveTask for active tasks, or
  // after the first time the panel is opened for completed tasks).
  const { data: cached } = useTaskDetailCache(task.id)

  const isLive = task.status === 'pending' || task.status === 'running'
  const events = detail?.event_log ?? cached?.event_log ?? []

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-blue-500 hover:underline"
      >
        {open ? 'Hide log' : `View log${events.length ? ` (${events.length})` : ''}`}
      </button>
      {open && (
        <div className="mt-2 bg-gray-50 rounded p-2 border border-gray-100">
          <TaskEventLog events={events} live={isLive} />
        </div>
      )}
    </div>
  )
}

const TASK_DESCRIPTIONS: Record<TaskType, string> = {
  scan: 'Connects to the SFTP server and lists remote files. New files are recorded in the database with status DISCOVERED. No files are downloaded.',
  download: 'Downloads all DISCOVERED files from the SFTP server to the local staging directory.',
  match: 'Parses filenames of DOWNLOADED files using regex and (optionally) LLM, then matches them to shows and episodes in the database.',
  route: 'Moves all MATCHED files from the staging directory to their final media library path. Creates season subdirectories as needed.',
  sync: 'Runs the full pipeline in sequence: Scan → Download → Match → Route.',
  import: 'Imports episode file paths from a text file, matching them to shows and episodes via TMDB lookup.',
  db_import: 'Imports show and episode metadata from a structured CSV or database export.',
  rss_import: 'Downloads the remote YaRSS2 config and syncs feeds and subscriptions into the database.',
  rss_publish: 'Composes the Jidou database state into a YaRSS2 config and uploads it to the remote server.',
  seed: 'One-time baseline: marks all pre-existing SFTP files as SEEDED so they are never re-downloaded.',
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
// 'seed' is intentionally excluded — it is triggered from Settings, not here.
const TYPE_OPTIONS: (TaskType | '')[] = ['', 'scan', 'download', 'match', 'route', 'sync', 'import', 'db_import', 'rss_import', 'rss_publish']

export default function Tasks() {
  const [taskType, setTaskType] = useState<TaskType>('scan')
  const [dryRun, setDryRun] = useState(false)

  const [filterType, setFilterType] = useState<TaskType | ''>('')
  const [pageSize, setPageSize] = useState(20)
  const [maxRecords, setMaxRecords] = useState<number | null>(200)
  const [page, setPage] = useState(0)

  const offset = page * pageSize
  const params = { limit: pageSize, offset, taskType: filterType || undefined }

  const { data: tasks = [], isLoading } = useTasks(params)
  const { data: countData } = useTaskCount(filterType || undefined)
  const total = countData?.total
  const effectiveTotal = total !== undefined
    ? (maxRecords !== null ? Math.min(total, maxRecords) : total)
    : undefined
  const totalPages = Math.max(1, Math.ceil((effectiveTotal ?? 1) / pageSize))

  // Clamp page when total shrinks (e.g. after cancel or refetch)
  useEffect(() => {
    if (page >= totalPages) setPage(Math.max(0, totalPages - 1))
  }, [totalPages, page])

  const triggerTask = useTriggerTask()
  const cancelTask = useCancelTask()

  const { data: activeTasks = [] } = useActiveTasks()

  function handleFilterChange(type: TaskType | '') {
    setFilterType(type)
    setPage(0)
  }

  function handlePageSizeChange(size: number) {
    setPageSize(size)
    setPage(0)
  }

  function handleMaxRecordsChange(val: string) {
    setMaxRecords(val === 'all' ? null : Number(val))
    setPage(0)
  }

  return (
    <div className="space-y-6">
      {activeTasks.map((t) => (
        <LiveTask key={t.id} taskId={t.id} />
      ))}

      <h1 className="text-2xl font-bold">Tasks</h1>

      {/* Trigger panel */}
      <div className="bg-white rounded-lg shadow p-4 space-y-3">
        <div className="flex items-end gap-4 flex-wrap">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Task type</label>
            <select
              value={taskType}
              onChange={(e) => setTaskType(e.target.value as TaskType)}
              className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {(['scan', 'download', 'match', 'route', 'sync'] as TaskType[]).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              className="rounded"
            />
            Dry run
          </label>
          <button
            onClick={() => triggerTask.mutate({ task_type: taskType, dry_run: dryRun })}
            disabled={triggerTask.isPending}
            className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            Run
          </button>
          {triggerTask.isError && (
            <p className="text-red-600 text-xs">{(triggerTask.error as Error).message}</p>
          )}
        </div>
        <p className="text-xs text-gray-500">{TASK_DESCRIPTIONS[taskType]}</p>
      </div>

      {/* List controls */}
      <div className="flex items-center gap-4 flex-wrap">
        <div>
          <label className="text-xs text-gray-500 mr-2">Filter by type</label>
          <select
            value={filterType}
            onChange={(e) => handleFilterChange(e.target.value as TaskType | '')}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>{t || 'All types'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mr-2">Per page</label>
          <select
            value={pageSize}
            onChange={(e) => handlePageSizeChange(Number(e.target.value))}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500 mr-2">Max records</label>
          <select
            value={maxRecords === null ? 'all' : String(maxRecords)}
            onChange={(e) => handleMaxRecordsChange(e.target.value)}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {[1, 5, 10, 25, 50, 100, 200, 500].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
            <option value="all">All</option>
          </select>
        </div>
        <span className="text-xs text-gray-500 ml-auto">
          {total === undefined ? '—' : (
            maxRecords !== null && total > maxRecords
              ? `${maxRecords} of ${total} task${total !== 1 ? 's' : ''}`
              : `${total} task${total !== 1 ? 's' : ''}`
          )}
          {filterType ? ` · ${filterType}` : ''}
        </span>
      </div>

      {/* Task list */}
      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : tasks.length === 0 ? (
        <p className="text-gray-500 text-sm">No tasks found.</p>
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => (
            <div key={t.id} className="bg-white rounded-lg shadow p-4">
              <TaskProgressBar
                task={t}
                onCancel={
                  t.status === 'pending' || t.status === 'running'
                    ? () => cancelTask.mutate(t.id)
                    : undefined
                }
              />
              <p className="text-xs text-gray-400 mt-1">
                Started {new Date(t.created_at).toLocaleString()}
                {t.completed_at && ` · Finished ${new Date(t.completed_at).toLocaleString()}`}
              </p>
              <TaskLogPanel task={t} />
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button
            onClick={() => setPage(0)}
            disabled={page === 0}
            className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            «
          </button>
          <button
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
            className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            ‹
          </button>
          <span className="text-gray-600">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            ›
          </button>
          <button
            onClick={() => setPage(totalPages - 1)}
            disabled={page >= totalPages - 1}
            className="px-2 py-1 border rounded disabled:opacity-40 hover:bg-gray-50"
          >
            »
          </button>
        </div>
      )}
    </div>
  )
}
