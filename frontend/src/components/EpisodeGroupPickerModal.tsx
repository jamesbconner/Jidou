import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { useEpisodeGroups, useApplyEpisodeGroup } from '@/hooks/useShows'
import type { ShowRead, EpisodeGroupSummary } from '@/types/api'

interface Props {
  show: ShowRead
  onClose: () => void
}

interface ApplySummary {
  episodes_added: number
  episodes_removed: number
  orphaned_file_count: number
}

export function EpisodeGroupPickerModal({ show, onClose }: Props) {
  const { data: groups, isLoading, isError } = useEpisodeGroups(show.id)
  const applyGroup = useApplyEpisodeGroup(show.id)
  const [pending, setPending] = useState<EpisodeGroupSummary | null>(null)
  const [applied, setApplied] = useState<ApplySummary | null>(null)

  function handleConfirmApply() {
    if (!pending) return
    applyGroup.mutate(pending.id, {
      onSuccess: (data) => {
        setApplied({
          episodes_added: data.episodes_added,
          episodes_removed: data.episodes_removed,
          orphaned_file_count: data.orphaned_file_count,
        })
      },
    })
    setPending(null)
  }

  return (
    <Modal
      onClose={onClose}
      tone="light"
      maxWidth="2xl"
      ariaLabel={`Choose episode grouping for ${show.title}`}
      className="flex flex-col max-h-[90vh]"
    >
      <div className="flex items-center justify-between px-5 py-4 border-b">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 truncate">
          Episode Grouping — {show.title}
        </h2>
        <ModalCloseButton onClose={onClose} leftGap />
      </div>

      <div className="overflow-y-auto flex-1 px-5 py-4 space-y-3">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Switch this show&apos;s episode list to an alternate TMDB grouping — e.g. a
          combined-episode broadcast order. Applying a grouping replaces the current episode
          list: tracked/watched status on removed episodes is preserved as a resolvable Data
          Quality record, and affected files will need to be relinked via &quot;Scan Local
          Files&quot;.
        </p>

        {applyGroup.isError && (
          <p className="text-xs text-red-600 dark:text-red-400">
            {(applyGroup.error as Error).message}
          </p>
        )}
        {applied && (
          <p className="text-xs text-green-600 dark:text-green-400">
            Applied: {applied.episodes_added} episode{applied.episodes_added === 1 ? '' : 's'}{' '}
            added, {applied.episodes_removed} removed
            {applied.orphaned_file_count > 0
              ? `, ${applied.orphaned_file_count} file${applied.orphaned_file_count === 1 ? '' : 's'} need rescanning`
              : ''}
            .
          </p>
        )}

        {isLoading && (
          <p className="text-sm text-gray-500 dark:text-gray-400">Loading groupings…</p>
        )}
        {isError && (
          <p className="text-sm text-red-600 dark:text-red-400">
            Failed to load episode groupings — check server logs.
          </p>
        )}
        {groups && groups.length === 0 && (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">
            No alternate episode groupings available for this show on TMDB.
          </p>
        )}
        {groups && groups.length > 0 && (
          <ul className="divide-y border rounded-lg dark:border-gray-700">
            {groups.map((g) => (
              <li key={g.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-sm text-gray-900 dark:text-gray-100 truncate">{g.name}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {g.episode_count} episode{g.episode_count === 1 ? '' : 's'} · {g.group_count}{' '}
                    group{g.group_count === 1 ? '' : 's'}
                  </p>
                </div>
                <button
                  onClick={() => setPending(g)}
                  disabled={g.is_active || applyGroup.isPending}
                  className="shrink-0 text-xs border rounded px-2 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
                >
                  {g.is_active ? 'Active' : 'Apply'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-end gap-2 px-5 py-3 border-t">
        <Button onClick={onClose} variant="primary" tone="light" size="md">
          Done
        </Button>
      </div>

      {pending && (
        <ConfirmDialog
          title="Apply alternate episode grouping?"
          description={`Switch to "${pending.name}"? This replaces the show's episode list. Tracked/watched status on removed episodes will need to be resolved via Data Quality, and affected files will need rescanning.`}
          confirmLabel="Apply"
          onConfirm={handleConfirmApply}
          onCancel={() => setPending(null)}
        />
      )}
    </Modal>
  )
}
