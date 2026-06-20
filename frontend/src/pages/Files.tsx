import { useState, useRef } from 'react'
import { useFiles, useRematchFile } from '@/hooks/useFiles'
import { fileKeys } from '@/hooks/useFiles'
import { FileStatusBadge } from '@/components/FileStatusBadge'
import { api } from '@/api/client'
import { useQueryClient, useMutation } from '@tanstack/react-query'
import type { FileRead, FileStatus } from '@/types/api'

const STATUS_OPTIONS: (FileStatus | '')[] = ['', 'pending', 'downloading', 'downloaded', 'routing', 'routed', 'error']

function InlineShowId({ fileId, showId }: { fileId: number; showId: number | null }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(showId?.toString() ?? '')
  const cancelRef = useRef(false)
  const qc = useQueryClient()
  const patch = useMutation({
    mutationFn: (newShowId: number | null) =>
      api.patch<FileRead>(`/files/${fileId}`, { show_id: newShowId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: fileKeys.all }),
  })

  function commit() {
    if (cancelRef.current) { cancelRef.current = false; return }
    setEditing(false)
    if (value === '') {
      if (showId !== null) patch.mutate(null)
      return
    }
    const parsed = parseInt(value, 10)
    if (isNaN(parsed) || parsed <= 0) {
      setValue(showId?.toString() ?? '')
      return
    }
    if (parsed !== showId) patch.mutate(parsed)
  }

  if (!editing) {
    return (
      <button
        onClick={() => { setValue(showId?.toString() ?? ''); setEditing(true) }}
        className="text-gray-500 hover:text-blue-600 hover:underline text-left"
        title="Click to assign show"
      >
        {showId ?? '—'}
      </button>
    )
  }

  return (
    <input
      type="number"
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') { cancelRef.current = true; setValue(showId?.toString() ?? ''); setEditing(false) }
      }}
      className="border rounded px-1 py-0.5 text-xs w-20 focus:outline-none focus:ring-1 focus:ring-blue-500"
    />
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

export default function Files() {
  const [statusFilter, setStatusFilter] = useState<FileStatus | ''>('')
  const { data: files = [], isLoading } = useFiles(statusFilter || undefined)
  const rematch = useRematchFile()

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Files</h1>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as FileStatus | '')}
          className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <p className="text-gray-400 text-sm">Loading…</p>
      ) : files.length === 0 ? (
        <p className="text-gray-500 text-sm">No files found.</p>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
              <tr>
                <th className="px-4 py-2 text-left">Filename</th>
                <th className="px-4 py-2 text-left">Size</th>
                <th className="px-4 py-2 text-left">Status</th>
                <th className="px-4 py-2 text-left">Show</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y">
              {files.map((f) => (
                <tr key={f.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-mono text-xs max-w-xs truncate">{f.original_filename}</td>
                  <td className="px-4 py-2 text-gray-500">{formatBytes(f.file_size)}</td>
                  <td className="px-4 py-2">
                    <FileStatusBadge status={f.status} />
                  </td>
                  <td className="px-4 py-2">
                    <InlineShowId fileId={f.id} showId={f.show_id} />
                  </td>
                  <td className="px-4 py-2 text-right">
                    {f.show_id != null && (
                      <button
                        onClick={() => rematch.mutate({ id: f.id, payload: { method: 'auto' } })}
                        disabled={rematch.isPending}
                        className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                      >
                        Re-match
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
