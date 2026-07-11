import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { toHostPath, toContainerPath, parseContainerPath } from '@/utils/paths'
import type { AppConfig, ContentType } from '@/types/api'

export function EditPathModal({
  current,
  onSave,
  onClose,
  isPending,
}: {
  current: string | null
  onSave: (path: string | null) => void
  onClose: () => void
  isPending: boolean
}) {
  const { data: config } = useQuery({
    queryKey: ['config'],
    queryFn: () => api.get<AppConfig>('/config'),
    staleTime: 60_000,
  })

  const mediaPaths = config?.media_paths
  const parsed = mediaPaths ? parseContainerPath(current, mediaPaths) : null
  const [contentType, setContentType] = useState<ContentType>(parsed?.contentType ?? 'tv')
  const [folderName, setFolderName] = useState(parsed?.folderName ?? '')

  // Re-parse when mediaPaths loads after mount.
  useEffect(() => {
    if (!mediaPaths) return
    const p = parseContainerPath(current, mediaPaths)
    setContentType(p.contentType)
    setFolderName(p.folderName)
  }, [mediaPaths]) // eslint-disable-line react-hooks/exhaustive-deps

  const hostPreview = mediaPaths && folderName.trim()
    ? toHostPath(toContainerPath(contentType, folderName.trim(), mediaPaths), mediaPaths)
    : null

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!mediaPaths) return
    if (!folderName.trim()) { onSave(null); return }
    onSave(toContainerPath(contentType, folderName.trim(), mediaPaths))
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-lg mx-4">
        <h3 className="font-semibold mb-4">Edit Local Path</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Content type — determines which volume base is used */}
          <div className="space-y-1">
            <label className="text-sm text-gray-600">Content type</label>
            <div className="flex gap-4">
              {(['anime', 'tv', 'movie'] as ContentType[]).map((t) => (
                <label key={t} className="flex items-center gap-1.5 text-sm cursor-pointer">
                  <input
                    type="radio"
                    name="edit_content_type"
                    value={t}
                    checked={contentType === t}
                    onChange={() => setContentType(t)}
                    className="accent-blue-600"
                  />
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </label>
              ))}
            </div>
          </div>

          {/* Show folder name */}
          <div className="space-y-1">
            <label className="text-sm text-gray-600">Show folder name</label>
            <input
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
              className="border rounded px-3 py-2 text-sm w-full font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Show Name"
              autoFocus
            />
            {hostPreview && (
              <p className="text-xs text-gray-500 font-mono">{hostPreview}</p>
            )}
          </div>

          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={onClose}
              disabled={isPending}
              className="px-4 py-2 text-sm border rounded hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending || !mediaPaths}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {isPending ? 'Saving…' : folderName.trim() ? 'Save' : 'Clear path'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
