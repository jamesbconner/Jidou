import { api } from '@/api/client'
import { useActiveTasks, useTask, useCancelTask } from '@/hooks/useTasks'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import { useQuery } from '@tanstack/react-query'
import type { AdminStats } from '@/types/api'

function LiveTask({ taskId }: { taskId: number }) {
  const { data: task } = useTask(taskId)
  useTaskProgress(task?.celery_task_id ?? null)
  return null
}

export default function Dashboard() {
  const { data: activeTasks = [] } = useActiveTasks()
  const { data: stats } = useQuery({
    queryKey: ['admin', 'stats'],
    queryFn: () => api.get<AdminStats>('/admin/stats'),
  })
  const cancelTask = useCancelTask()

  return (
    <div className="space-y-8">
      {/* Mount WebSocket listeners for active tasks */}
      {activeTasks.map((t) => (
        <LiveTask key={t.id} taskId={t.id} />
      ))}

      <h1 className="text-2xl font-bold">Dashboard</h1>

      {/* Stats row */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Shows', value: stats.shows },
            { label: 'Episodes', value: stats.episodes },
            { label: 'Files', value: stats.downloaded_files },
            { label: 'Tasks', value: stats.background_tasks },
          ].map(({ label, value }) => (
            <div key={label} className="bg-white rounded-lg shadow p-4">
              <p className="text-sm text-gray-500">{label}</p>
              <p className="text-2xl font-bold">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Active tasks */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Active Tasks</h2>
        {activeTasks.length === 0 ? (
          <p className="text-gray-500 text-sm">No active tasks.</p>
        ) : (
          <div className="space-y-3">
            {activeTasks.map((t) => (
              <div key={t.id} className="bg-white rounded-lg shadow p-4">
                <TaskProgressBar
                  task={t}
                  onCancel={() => cancelTask.mutate(t.id)}
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
