import { useState } from 'react'
import { Link } from 'react-router'
import { useFeedEntries, useRefreshFeedEntries } from '@/hooks/useRss'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Badge'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { AddShowFromFeedPane } from '@/components/AddShowFromFeedPane'
import type { FeedEntryGroupRead, RssFeedRead } from '@/types/api'

type GroupStatus = 'new' | 'in_library' | 'subscribed'
type Filter = 'unsubscribed' | 'subscribed' | 'all'

export function groupStatus(g: FeedEntryGroupRead): GroupStatus {
  if (g.existing_subscription_id != null) return 'subscribed'
  if (g.library_show != null) return 'in_library'
  return 'new'
}

const pad = (n: number) => String(n).padStart(2, '0')

function range(prefix: string, min: number | null | undefined, max: number | null | undefined) {
  if (min == null || max == null) return ''
  return min === max ? `${prefix}${pad(min)}` : `${prefix}${pad(min)}–${prefix}${pad(max)}`
}

/** "S02 E05–E07" style label for a group's season/episode span; '' when unparsed. */
export function spanLabel(g: FeedEntryGroupRead): string {
  return [range('S', g.season_min, g.season_max), range('E', g.episode_min, g.episode_max)]
    .filter(Boolean)
    .join(' ')
}

const STATUS_BADGE: Record<GroupStatus, { label: string; color: string }> = {
  new: {
    label: 'New',
    color: 'bg-[var(--color-ocean-100)] text-[var(--color-ocean-700)] dark:bg-[var(--color-ocean-900)]/40 dark:text-[var(--color-ocean-300)]',
  },
  in_library: {
    label: 'In library',
    color: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  },
  subscribed: {
    label: 'Subscribed',
    color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',
  },
}

function GroupRow({
  group,
  feed,
  onAdded,
}: {
  group: FeedEntryGroupRead
  feed: RssFeedRead
  onAdded: (parsedName: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const status = groupStatus(group)
  const badge = STATUS_BADGE[status]
  const span = spanLabel(group)
  const name = group.parsed_name ?? 'Unrecognized titles'
  // Needs a group key to re-read the feed's titles server-side.
  const canAdd = group.parsed_name != null && status !== 'subscribed'

  return (
    <li className="py-3 flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-gray-900 dark:text-gray-100">{name}</span>
          <Badge color={badge.color}>{badge.label}</Badge>
          {group.library_show && (
            <Link
              to={`/shows/${group.library_show.id}`}
              className="text-xs text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)] hover:underline"
            >
              View in library
            </Link>
          )}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
          {group.entry_count} {group.entry_count === 1 ? 'entry' : 'entries'}
          {span && ` · ${span}`}
        </p>
        <ul className="mt-1 space-y-0.5">
          {group.sample_titles.map((t) => (
            <li key={t} className="text-xs font-mono text-gray-500 dark:text-gray-400 truncate" title={t}>
              {t}
            </li>
          ))}
        </ul>
        {adding && (
          <AddShowFromFeedPane
            feed={feed}
            group={group}
            onDone={() => setAdding(false)}
            onAdded={() => group.parsed_name && onAdded(group.parsed_name)}
          />
        )}
      </div>
      {canAdd && !adding && (
        <Button variant="secondary" tone="light" size="sm" onClick={() => setAdding(true)}>
          Add…
        </Button>
      )}
    </li>
  )
}

export function FeedEntriesModal({ feed, onClose }: { feed: RssFeedRead; onClose: () => void }) {
  const { data, isLoading, error } = useFeedEntries(feed.id)
  const refresh = useRefreshFeedEntries(feed.id)
  const [filter, setFilter] = useState<Filter>('unsubscribed')
  // Groups added this session stay listed even though adding makes them
  // "Subscribed" (and so filtered out by default); otherwise the row, and the
  // outcome it is showing, would vanish the moment the entries refetch.
  const [added, setAdded] = useState<ReadonlySet<string>>(new Set())

  const groups = data?.groups ?? []
  const visible = groups.filter((g) => {
    if (g.parsed_name && added.has(g.parsed_name)) return true
    const subscribed = groupStatus(g) === 'subscribed'
    if (filter === 'all') return true
    return filter === 'subscribed' ? subscribed : !subscribed
  })
  const failure = refresh.error ?? error

  return (
    <Modal onClose={onClose} tone="light" maxWidth="3xl" className="flex flex-col max-h-[90vh]">
      <div className="flex items-center justify-between p-4 border-b">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Browse feed — {feed.name}
        </h2>
        <button
          onClick={onClose}
          aria-label="Close"
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-xl leading-none"
        >
          ✕
        </button>
      </div>

      <div className="overflow-y-auto p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SegmentedControl<Filter>
            aria-label="Filter groups"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'unsubscribed', label: 'Not subscribed' },
              { value: 'subscribed', label: 'Subscribed' },
              { value: 'all', label: 'All' },
            ]}
          />
          <div className="flex items-center gap-2">
            {data?.cached && (
              <span className="text-xs text-gray-400 dark:text-gray-500">Cached result</span>
            )}
            <Button
              variant="secondary"
              tone="light"
              size="sm"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || isLoading}
            >
              {refresh.isPending ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>
        </div>

        {isLoading && <p className="text-sm text-gray-500 dark:text-gray-400">Fetching feed…</p>}
        {failure && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            Could not load this feed: {failure.message}
          </p>
        )}
        {data?.malformed && (
          <p className="text-sm text-amber-600 dark:text-amber-400">
            The feed XML is malformed, so some entries may be missing.
          </p>
        )}
        {data?.truncated && (
          <p className="text-sm text-amber-600 dark:text-amber-400">
            This feed has more entries than can be shown; only the first {data.total_entries} are listed.
          </p>
        )}

        {data && groups.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">This feed has no entries.</p>
        )}
        {data && groups.length > 0 && visible.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Nothing matches this filter. Try “All”.
          </p>
        )}

        {visible.length > 0 && (
          <ul className="divide-y divide-gray-100 dark:divide-gray-800">
            {visible.map((g) => (
              <GroupRow
                key={g.parsed_name ?? '__unparsed__'}
                group={g}
                feed={feed}
                onAdded={(name) => setAdded((prev) => new Set(prev).add(name))}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-end p-4 border-t bg-gray-50 dark:bg-gray-900 rounded-b-lg">
        <Button onClick={onClose} variant="secondary" tone="light" size="md">
          Close
        </Button>
      </div>
    </Modal>
  )
}
