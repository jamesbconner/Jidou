import type { ReactNode } from 'react'
import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import type { useAppSettings, useUpdateAppSettings } from '@/hooks/useSettings'
import type { BannerStyle } from '@/hooks/useBannerStyle'
import type { AppSettingsPatch } from '@/types/api'

export interface FeaturesTabProps {
  appSettings: ReturnType<typeof useAppSettings>['data']
  updateAppSettings: ReturnType<typeof useUpdateAppSettings>
  bannerStyle: BannerStyle
  setBannerStyle: (style: BannerStyle) => void
}

type AppSettingsValue = NonNullable<FeaturesTabProps['appSettings']>

/** Boolean settings that have a plain on/off switch. */
type ToggleKey = {
  [K in keyof AppSettingsValue]-?: AppSettingsValue[K] extends boolean ? K : never
}[keyof AppSettingsValue] &
  keyof AppSettingsPatch

interface ToggleSpec {
  key: ToggleKey
  title: string
  description: ReactNode
  /** Shown while the settings are still loading. */
  fallback: boolean
}

const DASHBOARD_TOGGLES: ToggleSpec[] = [
  {
    key: 'show_adult_content',
    title: 'Show adult content',
    description: (
      <>
        Adult-flagged shows and episodes are always tracked; this only controls whether
        they appear in the dashboard&apos;s recently-added carousels.
      </>
    ),
    fallback: false,
  },
  {
    key: 'recent_episodes_enabled',
    title: 'Recently added episodes',
    description: <>Show the &quot;Recently Added Episodes&quot; carousel on the dashboard.</>,
    fallback: true,
  },
  {
    key: 'recent_movies_enabled',
    title: 'Recently added movies',
    description: <>Show the &quot;Recently Added Movies&quot; carousel on the dashboard.</>,
    fallback: true,
  },
  {
    key: 'recent_episodes_prefer_posters',
    title: 'Uniform episode artwork',
    description: (
      <>
        In the &quot;Recently Added Episodes&quot; carousel, always use the show poster
        instead of the episode still, so every card has the same shape. Episodes
        without a still already fall back to the poster.
      </>
    ),
    fallback: false,
  },
]

const PAGE_TOGGLES: ToggleSpec[] = [
  {
    key: 'dashboard_page_enabled',
    title: 'Dashboard',
    description: <>Show the dashboard page and its nav link.</>,
    fallback: true,
  },
  {
    key: 'calendar_enabled',
    title: 'Calendar',
    description: <>Show the airing calendar page and its nav link.</>,
    fallback: true,
  },
  {
    key: 'discover_enabled',
    title: 'Discover',
    description: <>Show the discover page and its nav link.</>,
    fallback: true,
  },
]

/** Title + hint text shared by every row of the tab. */
function SettingLabel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <span className="text-gray-700 dark:text-gray-300">
      {title}
      <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">{children}</span>
    </span>
  )
}

/** One labelled on/off switch row. */
function SettingToggle({
  title,
  description,
  checked,
  disabled,
  onChange,
}: {
  title: string
  description: ReactNode
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
      <SettingLabel title={title}>{description}</SettingLabel>
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
      />
    </label>
  )
}

/** A card of switches driven by a spec list; all lock while settings load or save. */
function ToggleList({
  specs,
  appSettings,
  locked,
  onPatch,
}: {
  specs: ToggleSpec[]
  appSettings: FeaturesTabProps['appSettings']
  locked: boolean
  onPatch: (patch: AppSettingsPatch) => void
}) {
  return (
    <>
      {specs.map((spec) => (
        <SettingToggle
          key={spec.key}
          title={spec.title}
          description={spec.description}
          checked={appSettings?.[spec.key] ?? spec.fallback}
          disabled={locked}
          onChange={(checked) => onPatch({ [spec.key]: checked })}
        />
      ))}
    </>
  )
}

/** The "Number of titles to show" input; clamps to 1-40 and ignores non-numbers. */
function SimilarCountInput({
  value,
  disabled,
  onChange,
}: {
  value: number
  disabled: boolean
  onChange: (count: number) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 text-sm">
      <SettingLabel title="Number of titles to show">
        How many similar titles to fetch and display (1–40).
      </SettingLabel>
      <input
        type="number"
        min={1}
        max={40}
        value={value}
        disabled={disabled}
        onChange={(e) => {
          const next = Number(e.target.value)
          if (!Number.isFinite(next)) return
          onChange(Math.min(40, Math.max(1, Math.round(next))))
        }}
        className="w-16 shrink-0 border rounded px-2 py-1 text-sm border-gray-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      />
    </label>
  )
}

/** Feature toggles (the Settings "Features" tab); hook state is owned by Settings. */
export function FeaturesTab({ appSettings, updateAppSettings, bannerStyle, setBannerStyle }: FeaturesTabProps) {
  const locked = !appSettings || updateAppSettings.isPending
  const similarEnabled = appSettings?.similar_titles_enabled ?? true
  const patch = (p: AppSettingsPatch) => updateAppSettings.mutate(p)

  return (
    <div className="space-y-8">
      {/* Show Detail — everything that changes how an individual show's detail page looks/behaves */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Show Detail</h2>
        {/* Banner style is browser-local (localStorage), not persisted via /api/settings */}
        <div className="flex items-start justify-between gap-4 text-sm">
          <SettingLabel title="Show detail banner">
            Backdrop treatment at the top of each show&apos;s detail page. Saved in this
            browser only.
          </SettingLabel>
          <SegmentedControl<BannerStyle>
            aria-label="Show detail banner style"
            className="shrink-0 flex-wrap justify-end"
            value={bannerStyle}
            onChange={setBannerStyle}
            options={[
              { value: 'hero', label: 'Hero' },
              { value: 'full', label: 'Full' },
              { value: 'none', label: 'None' },
            ]}
          />
        </div>
        <SettingToggle
          title="Similar titles"
          description={
            <>
              Show a &quot;Similar Titles&quot; carousel on each show&apos;s detail page,
              built from TMDB recommendations.
            </>
          }
          checked={similarEnabled}
          disabled={locked}
          onChange={(checked) => patch({ similar_titles_enabled: checked })}
        />
        <SettingToggle
          title="Include titles not in your library"
          description={
            <>
              Also show similar titles you don&apos;t track yet, with an Add action.
              When off, only titles already in your library appear.
            </>
          }
          checked={appSettings?.similar_titles_include_external ?? true}
          disabled={locked || !similarEnabled}
          onChange={(checked) => patch({ similar_titles_include_external: checked })}
        />
        <SimilarCountInput
          value={appSettings?.similar_titles_count ?? 12}
          disabled={locked || !similarEnabled}
          onChange={(count) => patch({ similar_titles_count: count })}
        />
      </Card>

      {/* Dashboard — only settings that affect the Dashboard page itself */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Dashboard</h2>
        <ToggleList specs={DASHBOARD_TOGGLES} appSettings={appSettings} locked={locked} onPatch={patch} />
      </Card>

      {/* Optional Pages — whole-page on/off switches, unrelated to Dashboard content */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Optional Pages</h2>
        <ToggleList specs={PAGE_TOGGLES} appSettings={appSettings} locked={locked} onPatch={patch} />
      </Card>
    </div>
  )
}
