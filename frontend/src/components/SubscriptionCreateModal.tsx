import { useState } from 'react'
import { useCreateRssSubscription } from '@/hooks/useRss'
import { Field } from '@/components/Field'
import type { RssFeedRead, RssSubscriptionCreate } from '@/types/api'

interface SubDraft {
  name: string
  feed_id: number | null
  show_id: number | null
  active: boolean
  regex_include: string
  regex_exclude: string
  regex_include_ignorecase: boolean
  regex_exclude_ignorecase: boolean
  download_location: string
  move_completed: string
  enabled_in_config: boolean
  label: string
}

export function SubscriptionCreateModal({ feeds, onClose }: { feeds: RssFeedRead[]; onClose: () => void }) {
  const create = useCreateRssSubscription()
  const [draft, setDraft] = useState<SubDraft>({
    name: '',
    feed_id: null,
    show_id: null,
    active: false,
    regex_include: '',
    regex_exclude: '',
    regex_include_ignorecase: true,
    regex_exclude_ignorecase: true,
    download_location: '',
    move_completed: '',
    enabled_in_config: false,
    label: '',
  })

  const set = <K extends keyof SubDraft>(key: K, value: SubDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleCreate = () => {
    if (!draft.name.trim()) return
    const body: RssSubscriptionCreate = {
      name: draft.name.trim(),
      feed_id: draft.feed_id,
      active: draft.active,
      regex_include: draft.regex_include || null,
      regex_exclude: draft.regex_exclude || null,
      regex_include_ignorecase: draft.regex_include_ignorecase,
      regex_exclude_ignorecase: draft.regex_exclude_ignorecase,
      download_location: draft.download_location || null,
      move_completed: draft.move_completed || null,
      enabled_in_config: draft.enabled_in_config,
      label: draft.label || null,
    }
    create.mutate(body, { onSuccess: onClose })
  }

  const textInput = (key: keyof SubDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  const monoInput = (key: keyof SubDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400"
    />
  )

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900">New Subscription</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Name *">{textInput('name', 'e.g. My Show S01')}</Field>
            <Field label="RSS Feed">
              <select
                value={draft.feed_id ?? ''}
                onChange={(e) => set('feed_id', e.target.value ? Number(e.target.value) : null)}
                className="w-full border rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                <option value="">— None —</option>
                {feeds.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </Field>
          </div>

          <div className="space-y-3">
            <span className="text-xs font-medium text-gray-600">Regex Patterns</span>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Include</label>
              {monoInput('regex_include', 'e.g. 1080p|720p')}
              <label className="flex items-center gap-2 text-xs text-gray-500 mt-1 cursor-pointer">
                <input type="checkbox" checked={draft.regex_include_ignorecase} onChange={(e) => set('regex_include_ignorecase', e.target.checked)} className="rounded" />
                Case-insensitive
              </label>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Exclude</label>
              {monoInput('regex_exclude', 'e.g. FRENCH|GERMAN')}
              <label className="flex items-center gap-2 text-xs text-gray-500 mt-1 cursor-pointer">
                <input type="checkbox" checked={draft.regex_exclude_ignorecase} onChange={(e) => set('regex_exclude_ignorecase', e.target.checked)} className="rounded" />
                Case-insensitive
              </label>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Download Location" note="Leave blank to use feed default">{textInput('download_location')}</Field>
            <Field label="Move Completed" note="Leave blank to use feed default">{textInput('move_completed')}</Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Label">{textInput('label', 'e.g. TV')}</Field>
            <div className="flex flex-col gap-2 justify-end pb-1">
              <label className="flex items-center gap-2 text-sm cursor-pointer" title="Included in the published YaRSS2 config.">
                <input type="checkbox" checked={draft.enabled_in_config} onChange={(e) => set('enabled_in_config', e.target.checked)} className="rounded" />
                Enabled in config
              </label>
              <label className="flex items-center gap-2 text-sm cursor-pointer" title="Jidou controls this flag. Active subscriptions are treated as live by the downloader.">
                <input type="checkbox" checked={draft.active} onChange={(e) => set('active', e.target.checked)} className="rounded" />
                Active
              </label>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 rounded-b-lg">
          <button onClick={onClose} className="px-4 py-1.5 text-sm rounded border border-gray-300 hover:bg-gray-100">Cancel</button>
          <button
            onClick={handleCreate}
            disabled={create.isPending || !draft.name.trim()}
            className="px-4 py-1.5 text-sm rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {create.isPending ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
