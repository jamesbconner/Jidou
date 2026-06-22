import { useState, useMemo } from 'react'
import { useTasks, useTaskCount, useTask, useTriggerTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import type { TaskType } from '@/types/api'

function LiveTask({ taskId }: { taskId: number }) {
  const { data: task } = useTask(taskId)
  useTaskProgress(task?.celery_task_id ?? null)
  return null
}

const TASK_DESCRIPTIONS: Record<TaskType, string> = {
  scan: 'Connects to the SFTP server and lists remote files. New files are recorded in the database with status DISCOVERED. No files are downloaded.',
  download: 'Downloads all DISCOVERED files from the SFTP server to the local staging directory.',
  match: 'Parses filenames of DOWNLOADED files using regex and (optionally) LLM, then matches them to shows and episodes in the database.',
  route: 'Moves all MATCHED files from the staging directory to their final media library path. Creates season subdirectories as needed.',
  sync: 'Runs the full pipeline in sequence: Scan → Download → Match → Route.',
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]
const TYPE_OPTIONS: (TaskType | '')[] = ['', 'scan', 'download', 'match', 'route', 'sync']

export default function Tasks() {
  const [taskType, setTaskType] = useState<TaskType>('scan')
  const [dryRun, setDryRun] = useState(false)

  const [filterType, setFilterType] = useState<TaskType | ''>('')
  const [pageSize, setPageSize] = useState(20)
  const [page, setPage] = useState(0)

  const offset = page * pageSize
  const params = { limit: pageSize, offset, taskType: filterType || undefined }

  const { data: tasks = [], isLoading } = useTasks(params)
  const { data: countData } = useTaskCount(filterType || undefined)
  const total = countData?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const triggerTask = useTriggerTask()
  const cancelTask = useCancelTask()

  const activeTasks = useMemo(
    () => tasks.filter((t) => t.status === 'pending' || t.status === 'running'),
    [tasks],
  )

  function handleFilterChange(type: TaskType | '') {
    setFilterType(type)
    setPage(0)
  }

  function handlePageSizeChange(size: number) {
    setPageSize(size)
    setPage(0)
  }

  return (
    <div className="space-y-6">
      {activeTasks.map((t) => (
        <LiveTask key={t.id} taskId={t.id} />
      ))}

      <h1 className="text-2xl font-bold">Tasks</h1>

      {/* Trigger panel */}
      <div className="bg-white rounded-lg shadow p-4 flex items-end gap-4 flex-wrap">
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

      <div className="bg-blue-50 border border-blue-100 rounded-lg p-4 text-sm text-blue-900">
        <p className="font-medium mb-1 capitalize">{taskType}</p>
        <p className="text-blue-800">{TASK_DESCRIPTIONS[taskType]}</p>
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
        <span className="text-xs text-gray-500 ml-auto">
          {total} task{total !== 1 ? 's' : ''}
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
