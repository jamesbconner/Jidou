import { useTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import type { TaskRead } from '@/types/api'

/**
 * Live task tracker: subscribes to WS progress for a single task. Lives in its
 * own module (rather than Settings.tsx) so DataTab can use it without a
 * circular import back to the page.
 */
export function LiveImportTask({ task }: { task: TaskRead }) {
  const { data: live } = useTask(task.id)
  useTaskProgress(task.celery_task_id, task.id)
  const t = live ?? task
  return (
    <div className="mt-4 space-y-2">
      <TaskProgressBar task={t} />
      {t.status === 'completed' && t.result_summary && (
        <pre className="text-xs bg-gray-50 dark:bg-gray-900 border rounded p-2 overflow-x-auto dark:text-gray-300">
          {JSON.stringify(t.result_summary, null, 2)}
        </pre>
      )}
      {t.status === 'failed' && (
        <p className="text-sm text-red-600 dark:text-red-400">{t.progress_message}</p>
      )}
    </div>
  )
}
