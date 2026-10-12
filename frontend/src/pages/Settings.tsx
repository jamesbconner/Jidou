import { useState } from 'react'
import { useConfig } from '@/hooks/useConfig'
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
      {tab === 'features' && <FeaturesTab />}
      {tab === 'services' && <ServicesTab config={config} />}
      {tab === 'data' && <DataTab />}
    </div>
  )
}
