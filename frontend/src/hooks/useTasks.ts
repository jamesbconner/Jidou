import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TaskList, TaskRead, TaskTrigger } from '@/types/api'

export const taskKeys = {
  all: ['tasks'] as const,
  list: () => [...taskKeys.all, 'list'] as const,
  detail: (id: number) => [...taskKeys.all, 'detail', id] as const,
}

export function useTasks() {
  return useQuery({
    queryKey: taskKeys.list(),
    // Fetch up to 100 tasks to avoid silent truncation; backend defaults to 20
    queryFn: () => api.get<TaskList[]>('/tasks?limit=100'),
    refetchInterval: 5000,
  })
}

export function useTask(id: number) {
  return useQuery({
    queryKey: taskKeys.detail(id),
    queryFn: () => api.get<TaskRead>(`/tasks/${id}`),
  })
}

export function useTriggerTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: TaskTrigger) => api.post<TaskRead>('/tasks/trigger', payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: taskKeys.list() }),
  })
}

export function useCancelTask() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.post<TaskRead>(`/tasks/${id}/cancel`),
    onSuccess: (data) => {
      qc.setQueryData(taskKeys.detail(data.id), data)
      qc.invalidateQueries({ queryKey: taskKeys.list() })
    },
  })
}
