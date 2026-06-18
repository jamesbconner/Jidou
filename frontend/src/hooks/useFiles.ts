import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { FileList, FileRead, FileMatchRequest, FileStatus } from '@/types/api'

export const fileKeys = {
  all: ['files'] as const,
  list: (status?: FileStatus) => [...fileKeys.all, 'list', status ?? 'all'] as const,
  detail: (id: number) => [...fileKeys.all, 'detail', id] as const,
}

export function useFiles(status?: FileStatus) {
  const params = status ? `?status=${status}` : ''
  return useQuery({
    queryKey: fileKeys.list(status),
    queryFn: () => api.get<FileList[]>(`/files${params}`),
  })
}

export function useFile(id: number) {
  return useQuery({
    queryKey: fileKeys.detail(id),
    queryFn: () => api.get<FileRead>(`/files/${id}`),
  })
}

export function useRematchFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: FileMatchRequest }) =>
      api.post<FileRead>(`/files/${id}/match`, payload),
    onSuccess: (data) => {
      qc.setQueryData(fileKeys.detail(data.id), data)
      // Invalidate all file queries (both list and detail, all status filters)
      qc.invalidateQueries({ queryKey: fileKeys.all })
    },
  })
}
