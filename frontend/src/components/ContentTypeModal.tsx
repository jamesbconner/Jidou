import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
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
    <Modal onClose={onClose} tone="light" maxWidth="sm" className="p-6">
        <h3 className="font-semibold mb-4 text-gray-900 dark:text-gray-100">Set Content Type</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <select
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
            className="border rounded px-3 py-2 text-sm w-full dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— clear —</option>
            <option value="anime">anime</option>
            <option value="tv">tv</option>
            <option value="movie">movie</option>
          </select>
          {error && (
            <p className="text-xs text-red-600 dark:text-red-400">{error.message}</p>
          )}
          <div className="flex gap-2 justify-end">
            <Button type="button" onClick={onClose} disabled={isPending} variant="secondary" tone="light" size="md">
              Cancel
            </Button>
            <Button type="submit" disabled={isPending} variant="primary" tone="light" size="md">
              {isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
    </Modal>
  )
}
