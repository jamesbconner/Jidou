import { useState, useMemo } from 'react'
import { useTasks, useTask, useTriggerTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import type { TaskType } from '@/types/api'

function LiveTask({ taskId }: { taskId: number }) {
  const { data: task } = useTask(taskId)
  useTaskProgress(task?.celery_task_id ?? null)
  return null
}

const SHOW_ID_TYPES = new Set<TaskType>(['download', 'match'])

export default function Tasks() {
  const { data: tasks = [], isLoading } = useTasks()
  const triggerTask = useTriggerTask()
  const cancelTask = useCancelTask()
  const [taskType, setTaskType] = useState<TaskType>('scan')
  const [dryRun, setDryRun] = useState(false)
  const [showIdInput, setShowIdInput] = useState('')

  const needsShowId = SHOW_ID_TYPES.has(taskType)
  const showIdParsed = showIdInput === '' ? null : parseInt(showIdInput, 10)
  const showIdValid = showIdInput === '' || (!isNaN(showIdParsed!) && showIdParsed! > 0)

  // Mount listeners for both pending and running tasks to capture updates from the start
  const activeTasks = useMemo(() => tasks.filter((t) => t.status === 'pending' || t.status === 'running'), [tasks])

  return (
    <div className="space-y-6">
      {/* Mount WebSocket listeners for all active tasks (pending and running) */}
      {activeTasks.map((t) => (
        <LiveTask key={t.id} taskId={t.id} />
      ))}

      <h1 className="text-2xl font-bold">Tasks</h1>

      <div className="bg-white rounded-lg shadow p-4 flex items-end gap-4 flex-wrap">
        <div>
          <label className="text-xs text-gray-500 block mb-1">Task type</label>
          <select
            value={taskType}
            onChange={(e) => { setTaskType(e.target.value as TaskType); setShowIdInput('') }}
            className="border rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {(['scan', 'download', 'match', 'sync'] as TaskType[]).map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        {needsShowId && (
          <div>
            <label className="text-xs text-gray-500 block mb-1">Show ID <span className="text-gray-400">(optional — blank runs all)</span></label>
            <input
              type="number"
              min="1"
              placeholder="e.g. 42"
              value={showIdInput}
              onChange={(e) => setShowIdInput(e.target.value)}
              className="border rounded px-2 py-1 text-sm w-28 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        )}
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
          onClick={() => triggerTask.mutate({
            task_type: taskType,
            dry_run: dryRun,
            ...(needsShowId && showIdParsed != null && { show_id: showIdParsed }),
          })}
          disabled={triggerTask.isPending || !showIdValid}
          className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
        >
          Run
        </button>
        {triggerTask.isError && (
          <p className="text-red-600 text-xs">{(triggerTask.error as Error).message}</p>
        )}
      </div>

      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => (
            <div key={t.id} className="bg-white rounded-lg shadow p-4">
              <TaskProgressBar
                task={t}
                onCancel={
                  (t.status === 'pending' || t.status === 'running')
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
    </div>
  )
}
