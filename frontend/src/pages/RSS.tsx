import { useState } from 'react'
import {
  useRssFeeds,
  useRssSubscriptions,
  useTriggerRssImport,
  useTriggerRssPublish,
  useRssDownload,
  useRssDiff,
  useRssImportTask,
  useRssPublishTask,
} from '@/hooks/useRss'
import { SubscriptionsTable } from '@/components/SubscriptionsTable'
import { FeedsTable } from '@/components/FeedsTable'
import { RecommendationsTab } from '@/components/RecommendationsTab'
import { RssDiffModal } from '@/components/RssDiffModal'
import { useLocalStorageState } from '@/hooks/useLocalStorage'
import { RssHeader } from '@/pages/rss/RssHeader'
import { SubscriptionFilters } from '@/pages/rss/SubscriptionFilters'
import {
  DEFAULT_RSS_FILTERS,
  filterSubscriptions,
  type RssFilterState,
} from '@/pages/rss/rssFilters'

type RssTab = 'subscriptions' | 'feeds' | 'recommendations'

function tabLabel(tab: RssTab, subCount: number, feedCount: number): string {
  if (tab === 'subscriptions') return `Subscriptions (${subCount})`
  if (tab === 'feeds') return `Feeds (${feedCount})`
  return 'Recommendations'
}

export default function RSS() {
  const [tab, setTab] = useState<RssTab>('subscriptions')

  // Persisted so filter choices survive navigating away and back, not just page reloads.
  const [filters, setFilters] = useLocalStorageState<RssFilterState>('jidou:rss-filters', DEFAULT_RSS_FILTERS)
  const patchFilters = (patch: Partial<RssFilterState>) => setFilters({ ...filters, ...patch })

  const [importTaskId, setImportTaskId] = useState<number | null>(null)
  const [publishTaskId, setPublishTaskId] = useState<number | null>(null)

  const { data: feeds = [] } = useRssFeeds()
  const { data: subs, isLoading } = useRssSubscriptions()
  const triggerImport = useTriggerRssImport()
  const triggerPublish = useTriggerRssPublish()
  const download = useRssDownload()
  const diff = useRssDiff()

  const { data: importTask } = useRssImportTask(importTaskId)
  const { data: publishTask } = useRssPublishTask(publishTaskId)

  const filteredSubs = filterSubscriptions(subs ?? [], filters)

  return (
    <div className="space-y-6">
      <RssHeader
        triggerImport={triggerImport}
        triggerPublish={triggerPublish}
        download={download}
        diff={diff}
        importTask={importTask}
        publishTask={publishTask}
        onImport={() => triggerImport.mutate(undefined, { onSuccess: (t) => setImportTaskId(t.id) })}
        onPublish={() => triggerPublish.mutate(undefined, { onSuccess: (t) => setPublishTaskId(t.id) })}
        onDownload={() => download.mutate()}
        onDiff={() => diff.mutate()}
      />

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-800">
        <nav className="-mb-px flex gap-6">
          {(['subscriptions', 'feeds', 'recommendations'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`pb-3 text-sm font-medium capitalize border-b-2 transition-colors ${
                tab === t
                  ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-500 dark:hover:text-gray-300 dark:hover:border-gray-700'
              }`}
            >
              {tabLabel(t, subs?.length ?? 0, feeds.length)}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {tab === 'subscriptions' && (
        <section>
          <SubscriptionFilters
            filters={filters}
            onChange={patchFilters}
            feeds={feeds}
            shown={filteredSubs.length}
            total={subs?.length ?? 0}
          />

          {isLoading ? (
            <p className="text-sm text-gray-400 dark:text-gray-500">Loading subscriptions…</p>
          ) : (
            <div className="border rounded-lg p-3">
              <SubscriptionsTable subs={filteredSubs} feeds={feeds} />
            </div>
          )}
        </section>
      )}

      {tab === 'feeds' && (
        <section>
          <div className="border rounded-lg p-3">
            <FeedsTable feeds={feeds} />
          </div>
        </section>
      )}

      {tab === 'recommendations' && <RecommendationsTab />}

      {diff.data && <RssDiffModal diff={diff.data} onClose={() => diff.reset()} />}
    </div>
  )
}
