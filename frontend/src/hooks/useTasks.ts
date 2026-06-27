import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TaskEvent, TaskList, TaskRead, TaskTrigger, TaskType } from '@/types/api'

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

/**
 * Merge a fresh server response with any WS events accumulated in the cache.
 *
 * Deduplicates by composite key (ts|level|msg) rather than ts alone so that
 * two distinct events emitted within the same millisecond are both preserved.
 * Any event in the cache whose key is absent from the server response is
 * appended — those are WS events that arrived during the network round-trip
 * and have not yet been persisted when the HTTP response was generated.
 */
function mergeEventLog(fresh: TaskRead, cached: TaskRead | undefined): TaskRead {
  if (!cached?.event_log?.length) return fresh
  const eventKey = (e: TaskEvent) => `${e.ts}|${e.level}|${e.msg}`
  const freshKeys = new Set((fresh.event_log ?? []).map(eventKey))
  const liveOnly = cached.event_log.filter((e) => !freshKeys.has(eventKey(e)))
  return { ...fresh, event_log: [...(fresh.event_log ?? []), ...liveOnly] }
}

/**
 * Fetch task detail. Merges the HTTP response with any WS events already in
 * the cache so refetches (e.g. on window focus from LiveTask) do not drop
 * events that arrived via WebSocket since the last server response.
 */
export function useTask(id: number) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: async () => {
      const fresh = await api.get<TaskRead>(`/tasks/${id}`)
      return mergeEventLog(fresh, qc.getQueryData<TaskRead>(taskKeys.detail(id)))
    },
    enabled: id > 0,
  })
}

/**
 * Fetch task detail for the log panel. Uses staleTime:0 so the merge queryFn
 * always runs when the panel opens, even if useTask cached the row recently.
 * refetchOnWindowFocus is disabled to avoid redundant refetches while the
 * panel is open.
 */
export function useTaskDetail(id: number) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: async () => {
      const fresh = await api.get<TaskRead>(`/tasks/${id}`)
      return mergeEventLog(fresh, qc.getQueryData<TaskRead>(taskKeys.detail(id)))
    },
    enabled: id > 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
  })
}

/**
 * Subscribes to an already-cached task detail without triggering a fetch.
 * Used by TaskLogPanel to reactively read event_log.length for the count
 * badge while the panel is closed.
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
