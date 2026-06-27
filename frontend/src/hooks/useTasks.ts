import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TaskList, TaskRead, TaskTrigger, TaskType } from '@/types/api'

export const taskKeys = {
  all: ['tasks'] as const,
  list: (params: TaskListParams) => [...taskKeys.all, 'list', params] as const,
  count: (taskType?: TaskType) => [...taskKeys.all, 'count', taskType] as const,
  detail: (id: number) => [...taskKeys.all, 'detail', id] as const,
}

export interface TaskListParams {
  limit: number
  offset: number
  taskType?: TaskType
}

export function useTasks(params: TaskListParams) {
  const qs = new URLSearchParams({
    limit: String(params.limit),
    offset: String(params.offset),
    ...(params.taskType ? { task_type: params.taskType } : {}),
  })
  return useQuery({
    queryKey: taskKeys.list(params),
    queryFn: () => api.get<TaskList[]>(`/tasks?${qs}`),
    refetchInterval: 5000,
  })
}

export function useActiveTasks() {
  return useQuery({
    queryKey: [...taskKeys.all, 'active'] as const,
    queryFn: () => api.get<TaskList[]>('/tasks?active_only=true&limit=100'),
    refetchInterval: 5000,
  })
}

export function useTaskCount(taskType?: TaskType) {
  const qs = taskType ? `?task_type=${taskType}` : ''
  return useQuery({
    queryKey: taskKeys.count(taskType),
    queryFn: () => api.get<{ total: number }>(`/tasks/count${qs}`),
    refetchInterval: 5000,
  })
}

export function useTask(id: number) {
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: () => api.get<TaskRead>(`/tasks/${id}`),
    enabled: id > 0,
  })
}

/**
 * Fetches a task detail and merges the response event_log with any live
 * WebSocket events already accumulated in the cache.  Without the merge a
 * stale HTTP response that started before newer WS events were persisted
 * would overwrite those events, making the live log jump backwards.
 */
export function useTaskDetail(id: number) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: async () => {
      const fresh = await api.get<TaskRead>(`/tasks/${id}`)
      const cached = qc.getQueryData<TaskRead>(taskKeys.detail(id))
      if (!cached?.event_log?.length) return fresh
      // Keep any WS events that arrived after the fetch started and are not
      // yet in the server response.
      const freshTs = new Set((fresh.event_log ?? []).map((e) => e.ts))
      const liveOnly = cached.event_log.filter((e) => !freshTs.has(e.ts))
      return { ...fresh, event_log: [...(fresh.event_log ?? []), ...liveOnly] }
    },
    enabled: id > 0,
    staleTime: 30_000,
  })
}

/**
 * Subscribes to an already-cached task detail without triggering a fetch.
 * Use this to reactively read event_log length for the count badge while
 * the log panel is closed.
 */
export function useTaskDetailCache(id: number) {
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: () => api.get<TaskRead>(`/tasks/${id}`),
    enabled: false,
    staleTime: Infinity,
  })
}

export function useTriggerTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: TaskTrigger) => api.post<TaskRead>('/tasks/trigger', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: taskKeys.all }),
  })
}

export function useCancelTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<TaskRead>(`/tasks/${id}/cancel`),
    onSuccess: (data) => {
      qc.setQueryData(taskKeys.detail(data.id), data)
      qc.invalidateQueries({ queryKey: taskKeys.all })
    },
  })
}
