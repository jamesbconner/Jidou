import { useMutation } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TaskRead } from '@/types/api'

export function useImportText() {
  return useMutation({
    mutationFn: ({
      file,
      contentType,
      dryRun,
    }: {
      file: File
      contentType: string
      dryRun: boolean
    }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('content_type', contentType)
      form.append('dry_run', String(dryRun))
      return api.postForm<TaskRead>('/import/text', form)
    },
  })
}

export function useExportDatabase() {
  return useMutation({
    mutationFn: async () => {
      const { blob, filename } = await api.downloadBlob('/export/database')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    },
  })
}

export function useImportDatabase() {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<TaskRead>('/import/database', form)
    },
  })
}
