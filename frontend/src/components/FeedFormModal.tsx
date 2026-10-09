import { useState } from 'react'
import { useCreateRssFeed, usePatchRssFeed } from '@/hooks/useRss'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/Field'
import type { RssFeedRead, RssFeedCreate, RssFeedUpdate } from '@/types/api'

interface FeedDraft {
  name: string
  url: string
  remote_key: string
  default_download_location: string
  default_move_completed: string
  regex_include_samples: { sample_name: string; hint: string }[]
  regex_exclude_hint: string
  no_exclude_needed: boolean
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
    regex_include_samples:
      feed?.regex_include_samples?.map((s) => ({ sample_name: s.sample_name, hint: s.hint })) ?? [],
    regex_exclude_hint: feed?.regex_exclude_hint ?? '',
    no_exclude_needed: feed?.regex_exclude_hint === '',
    active: feed?.active ?? true,
  })

  const set = <K extends keyof FeedDraft>(key: K, value: FeedDraft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const handleSave = () => {
    if (!draft.name.trim() || !draft.url.trim()) return
    // regex_exclude_hint distinguishes "" (feed explicitly needs no exclude
    // filter) from null (no guidance set) -- see suggest-regex prompt logic.
    const samples = draft.regex_include_samples
      .map((s) => ({ sample_name: s.sample_name.trim(), hint: s.hint.trim() }))
      .filter((s) => s.hint)
    const regexExcludeHint = draft.no_exclude_needed ? '' : draft.regex_exclude_hint.trim() || null
    if (isEdit) {
      const update: RssFeedUpdate = {
        name: draft.name.trim(),
        url: draft.url.trim(),
        remote_key: draft.remote_key.trim() || null,
        default_download_location: draft.default_download_location.trim() || null,
        default_move_completed: draft.default_move_completed.trim() || null,
        regex_include_samples: samples.length ? samples : null,
        regex_exclude_hint: regexExcludeHint,
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
        regex_include_samples: samples.length ? samples : null,
        regex_exclude_hint: regexExcludeHint,
        active: draft.active,
      }
      create.mutate(body, { onSuccess: onClose })
    }
  }

  const sampleInputClass =
    'w-full border rounded px-2 py-1.5 text-sm dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)]'
  const setSample = (i: number, patch: Partial<{ sample_name: string; hint: string }>) =>
    setDraft((d) => ({
      ...d,
      regex_include_samples: d.regex_include_samples.map((s, j) => (j === i ? { ...s, ...patch } : s)),
    }))
  const removeSample = (i: number) =>
    setDraft((d) => ({ ...d, regex_include_samples: d.regex_include_samples.filter((_, j) => j !== i) }))
  const addSample = () =>
    setDraft((d) => ({ ...d, regex_include_samples: [...d.regex_include_samples, { sample_name: '', hint: '' }] }))

  const isPending = create.isPending || patch.isPending

  const textInput = (key: keyof FeedDraft, placeholder = '') => (
    <input
      value={draft[key] as string}
      onChange={(e) => set(key, e.target.value)}
      placeholder={placeholder}
      className="w-full border rounded px-2 py-1.5 text-sm dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)]"
    />
  )

  return (
    <Modal onClose={onClose} tone="light" className="flex flex-col max-h-[90vh]">
        <div className="flex items-center justify-between p-5 border-b">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{isEdit ? 'Edit Feed' : 'New Feed'}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none">✕</button>
        </div>

        <div className="overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Name *">{textInput('name', 'e.g. ShowRSS')}</Field>
            <Field label="Remote Key" note="YaRSS2 feed key (e.g. 1, 2). Leave blank for manually-only feeds.">{textInput('remote_key', 'e.g. 1')}</Field>
          </div>
          <Field label="URL *">{textInput('url', 'https://…')}</Field>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Default Download Location" note="Used by subscriptions that don't override it.">{textInput('default_download_location')}</Field>
            <Field label="Default Move Completed" note="Used by subscriptions that don't override it.">{textInput('default_move_completed')}</Field>
          </div>
          <Field
            label="Regex Include Samples"
            note="Up to 3. Paste a real release title from this feed, then the regex_include that correctly matches it. Shown to the LLM suggester as worked examples (token order matters)."
          >
            <div className="space-y-2">
              {draft.regex_include_samples.map((s, i) => (
                <div key={i} className="flex items-start gap-2">
                  <div className="flex-1 space-y-1">
                    <input
                      value={s.sample_name}
                      onChange={(e) => setSample(i, { sample_name: e.target.value })}
                      placeholder="Sample name, e.g. Some.Show.S01E02.1080p.WEB-DL.mkv"
                      className={sampleInputClass}
                    />
                    <input
                      value={s.hint}
                      onChange={(e) => setSample(i, { hint: e.target.value })}
                      placeholder="Hint, e.g. ^Some.Show.*s\d{2}e\d{2}.*1080p.*"
                      className={sampleInputClass}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeSample(i)}
                    aria-label={`Remove sample ${i + 1}`}
                    className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-lg leading-none mt-1"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {draft.regex_include_samples.length < 3 && (
                <button type="button" onClick={addSample} className="text-xs text-[var(--color-ocean-500)] dark:text-[var(--color-ocean-400)] hover:underline">
                  + Add sample
                </button>
              )}
            </div>
          </Field>
          <Field
            label="Regex Exclude"
            note="Used as-is as the suggested regex_exclude for this feed's subscriptions."
          >
            <input
              value={draft.regex_exclude_hint}
              onChange={(e) => set('regex_exclude_hint', e.target.value)}
              disabled={draft.no_exclude_needed}
              placeholder="e.g. .*(720p|iNTERNAL|spanish|french|german).*"
              className="w-full border rounded px-2 py-1.5 text-sm dark:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-[var(--color-ocean-400)] disabled:bg-gray-100 dark:disabled:bg-gray-900 disabled:text-gray-400"
            />
            <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-300 mt-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={draft.no_exclude_needed}
                onChange={(e) => set('no_exclude_needed', e.target.checked)}
                className="rounded"
              />
              This feed&apos;s releases typically don&apos;t need an exclude filter
            </label>
          </Field>
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

        <div className="flex justify-end gap-2 p-4 border-t bg-gray-50 dark:bg-gray-900 rounded-b-lg">
          <Button onClick={onClose} variant="secondary" tone="light" size="md">Cancel</Button>
          <button
            onClick={handleSave}
            disabled={isPending || !draft.name.trim() || !draft.url.trim()}
            className="px-4 py-1.5 text-sm rounded bg-[var(--color-ocean-600)] text-white hover:bg-[var(--color-ocean-700)] dark:hover:bg-[var(--color-ocean-500)] disabled:opacity-50"
          >
            {isPending ? 'Saving…' : isEdit ? 'Save' : 'Create'}
          </button>
        </div>
    </Modal>
  )
}
