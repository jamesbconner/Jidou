import { useState } from 'react'
import type { ContentType } from '@/types/api'

export function ContentTypeModal({
  current,
  onSave,
  onClose,
  isPending,
  error,
}: {
  current: string | null
  onSave: (value: ContentType | null) => void
  onClose: () => void
  isPending: boolean
  error: Error | null
}) {
  const [draft, setDraft] = useState(current ?? '')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSave((draft || null) as ContentType | null)
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm mx-4">
        <h3 className="font-semibold mb-4">Set Content Type</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
            className="border rounded px-3 py-2 text-sm w-full focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— clear —</option>
            <option value="anime">anime</option>
            <option value="tv">tv</option>
            <option value="movie">movie</option>
          </select>
          {error && (
            <p className="text-xs text-red-600">{error.message}</p>
          )}
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
              disabled={isPending}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
