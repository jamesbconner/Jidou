import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api, type ApiError } from '@/api/client'
import type { ConnectionTestResult, TaskRead } from '@/types/api'

export type ConnectionService = 'tmdb' | 'sftp' | 'redis' | 'llm'

/**
 * On-demand connection test for one backend service. Kept as a hook so the
 * Settings page never touches the API client; the result lives on the mutation.
 */
export function useConnectionTest(service: ConnectionService) {
  return useMutation<ConnectionTestResult, ApiError, void>({
    mutationFn: () => api.post<ConnectionTestResult>(`/config/test/${service}`),
  })
}

/** One trigger mutation: POST the task and open the Tasks page highlighting it. */
function useTriggerMutation(taskType: string, dryRun: boolean) {
  const navigate = useNavigate()
  return useMutation<TaskRead, ApiError, void>({
    mutationFn: () => api.post<TaskRead>('/tasks/trigger', { task_type: taskType, dry_run: dryRun }),
    onSuccess: (task) => navigate(`/tasks?highlight=${task.id}`),
  })
}

/**
 * Dry-run and live triggers for a maintenance task. Both navigate to the Tasks
 * page highlighting the created task, exactly as the Settings buttons did inline.
 */
export function useTriggerWithDryRun(taskType: 'seed' | 'backfill_show_metadata') {
  const dryRun = useTriggerMutation(taskType, true)
  const live = useTriggerMutation(taskType, false)
  return { dryRun, live }
}
