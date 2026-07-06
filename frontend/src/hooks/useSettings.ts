import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { AppSettings, AppSettingsPatch } from '@/types/api'

export const settingsKeys = {
  all: ['settings'] as const,
}

export function useAppSettings() {
  return useQuery({
    queryKey: settingsKeys.all,
    queryFn: () => api.get<AppSettings>('/settings'),
  })
}

export function useUpdateAppSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: AppSettingsPatch) => api.patch<AppSettings>('/settings', payload),
    onSuccess: (settings) => {
      qc.setQueryData(settingsKeys.all, settings)
      // Adult-content visibility affects dashboard query results.
      qc.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}
