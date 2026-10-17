import { useState } from 'react'
import { useAdminHealth, useAdminCache, useFlushCache } from '@/hooks/useAdmin'
import { useAppSettings, useUpdateAppSettings } from '@/hooks/useSettings'
import { useBannerStyle } from '@/hooks/useBannerStyle'
import { useConfig } from '@/hooks/useConfig'
import { useConnectionTest, useTriggerWithDryRun } from '@/hooks/useSettingsActions'
import { DataTab } from './settings/DataTab'
import { FeaturesTab } from './settings/FeaturesTab'
import { GeneralTab } from './settings/GeneralTab'
import { ServicesTab } from './settings/ServicesTab'

type Tab = 'general' | 'features' | 'services' | 'data'

const TABS: { id: Tab; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'features', label: 'Features' },
  { id: 'services', label: 'Services' },
  { id: 'data', label: 'Data' },
]

/** Settings page shell: owns the tab bar and active-tab state; each tab is its own component. */
export default function Settings() {
  const [tab, setTab] = useState<Tab>('general')
  const { data: config } = useConfig()

  // Every stateful hook lives here, not in the tabs: a tab unmounts when the
  // user switches away, which would drop test results, flush messages and error
  // text and delay GET /admin/cache until the Services tab opens.
  const tests = {
    tmdb: useConnectionTest('tmdb'),
    sftp: useConnectionTest('sftp'),
    redis: useConnectionTest('redis'),
    llm: useConnectionTest('llm'),
  }
  const cache = useAdminCache()
  const flushCache = useFlushCache()
  const health = useAdminHealth()
  const { data: appSettings } = useAppSettings()
  const updateAppSettings = useUpdateAppSettings()
  // Browser-local UI preference (not backed by /api/settings).
  const [bannerStyle, setBannerStyle] = useBannerStyle()
  const seed = useTriggerWithDryRun('seed')
  const backfill = useTriggerWithDryRun('backfill_show_metadata')

  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === t
        ? 'border-[var(--color-ocean-600)] text-[var(--color-ocean-600)] dark:border-[var(--color-ocean-400)] dark:text-[var(--color-ocean-400)]'
        : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300'
    }`

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold dark:text-gray-100">Settings</h1>

      {/* Tabs */}
      <div className="flex border-b">
        {TABS.map(({ id, label }) => (
          <button key={id} className={tabCls(id)} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'general' && config && <GeneralTab config={config} />}
      {tab === 'features' && (
        <FeaturesTab
          appSettings={appSettings}
          updateAppSettings={updateAppSettings}
          bannerStyle={bannerStyle}
          setBannerStyle={setBannerStyle}
        />
      )}
      {tab === 'services' && (
        <ServicesTab
          config={config}
          cache={cache}
          flushCache={flushCache}
          health={health}
          tests={tests}
          appSettings={appSettings}
          updateAppSettings={updateAppSettings}
        />
      )}
      {tab === 'data' && <DataTab seed={seed} backfill={backfill} />}
    </div>
  )
}
