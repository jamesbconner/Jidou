import { useState } from 'react'
import { useCreateRssFeed, usePatchRssFeed } from '@/hooks/useRss'
import { Field } from '@/components/Field'
import type { RssFeedRead, RssFeedCreate, RssFeedUpdate } from '@/types/api'

interface FeedDraft {
  name: string
  url: string
  remote_key: string
  default_download_location: string
  default_move_completed: string
  active: boolean
}

export function FeedFormModal({ feed, onClose }: { feed: RssFeedRead | null; onClose: () => void }) {
  const create = useCreateRssFeed()
  const patch = usePatchRssFeed()
  const isEdit = feed !== null

  const [draft, setDraft] = useState<FeedDraft>({
    name: feed?.name ?? '',
    url: feed?.url ?? '',
    remote_key: feed?.remote_key ?? '',
    default_download_location: feed?.default_download_location ?? '',
    default_move_completed: feed?.default_move_completed ?? '',
    active: feed?.active ?? true,
  })

  const set = <K extends keyof FeedDraft>(key: K, value: FeedDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleSave = () => {
    if (!draft.name.trim() || !draft.url.trim()) return
    if (isEdit) {
      const update: RssFeedUpdate = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        remote_key: draft.remote_key.trim() || null,
        default_download_location: draft.default_download_location.trim() || null,
        default_move_completed: draft.default_move_completed.trim() || null,
        active: draft.active,
      }
      patch.mutate({ id: feed.id, update }, { onSuccess: onClose })
    } else {
      const body: RssFeedCreate = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        remote_key: draft.remote_key.trim() || null,
        default_download_location: draft.default_download_location.trim() || null,
        default_move_completed: draft.default_move_completed.trim() || null,
        active: draft.active,
      }
      create.mutate(body, { onSuccess: onClose })
    }
  }

  const isPending = create.isPending || patch.isPending

  const textInput = (key: keyof FeedDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900">{isEdit ? 'Edit Feed' : 'New Feed'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Name *">{textInput('name', 'e.g. ShowRSS')}</Field>
            <Field label="Remote Key" note="YaRSS2 feed key (e.g. 1, 2). Leave blank for manually-only feeds.">{textInput('remote_key', 'e.g. 1')}</Field>
          </div>
          <Field label="URL *">{textInput('url', 'https://…')}</Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Default Download Location" note="Used by subscriptions that don't override it.">{textInput('default_download_location')}</Field>
            <Field label="Default Move Completed" note="Used by subscriptions that don't override it.">{textInput('default_move_completed')}</Field>
          </div>
          <label
            className="flex items-center gap-2 text-sm cursor-pointer"
            title="Inactive feeds are excluded from the published YaRSS2 config."
          >
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(e) => set('active', e.target.checked)}
              className="rounded"
            />
            Active (included in published config)
          </label>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
          <button
            onClick={handleSave}
            disabled={isPending || !draft.name.trim() || !draft.url.trim()}
            className="px-4 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {isPending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
