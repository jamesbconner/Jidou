import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AppConfig } from '@/types/api'

export const configKeys = {
  all: ['config'] as const,
}

/**
 * The server's read-only runtime config (media paths, feature flags).
 *
 * Seven components used to declare this query inline; one shared hook keeps
 * the key and the 60 s staleTime identical everywhere, so every observer
 * shares a single cache entry and a single request.
 */
export function useConfig() {
  return useQuery({
    queryKey: configKeys.all,
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })
}
