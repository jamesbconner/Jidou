import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { HealthCheck, CacheStats } from '@/types/api'

export const adminKeys = {
  health: ['admin', 'health'] as const,
  cache: ['admin', 'cache'] as const,
}

export function useAdminHealth() {
  return useQuery({
    queryKey: adminKeys.health,
    queryFn: () => api.get<HealthCheck>('/admin/health'),
    enabled: false,
  })
}

export function useAdminCache() {
  return useQuery({
    queryKey: adminKeys.cache,
    queryFn: () => api.get<CacheStats>('/admin/cache'),
  })
}

export function useFlushCache() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<{ ok: boolean; cleared: number }>('/admin/cache/flush'),
    onSuccess: () => qc.invalidateQueries({ queryKey: adminKeys.cache }),
  })
}
