import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAppSettings, useUpdateAppSettings } from '@/hooks/useSettings'
import { useBannerStyle } from '@/hooks/useBannerStyle'
import type { BannerStyle } from '@/hooks/useBannerStyle'

/** Feature toggles (the Settings "Features" tab): app settings plus the browser-local banner style. */
export function FeaturesTab() {
  const { data: appSettings } = useAppSettings()
  const updateAppSettings = useUpdateAppSettings()

  // Browser-local UI preference (not backed by /api/settings).
  const [bannerStyle, setBannerStyle] = useBannerStyle()

  return (
    <div className="space-y-8">
      {/* Show Detail — everything that changes how an individual show's detail page looks/behaves */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Show Detail</h2>
        {/* Banner style is browser-local (localStorage), not persisted via /api/settings */}
        <div className="flex items-start justify-between gap-4 text-sm">
          <span className="text-gray-700 dark:text-gray-300">
            Show detail banner
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Backdrop treatment at the top of each show&apos;s detail page. Saved in this
              browser only.
            </span>
          </span>
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
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Similar titles
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show a &quot;Similar Titles&quot; carousel on each show&apos;s detail page,
              built from TMDB recommendations.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.similar_titles_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ similar_titles_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Include titles not in your library
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Also show similar titles you don&apos;t track yet, with an Add action.
              When off, only titles already in your library appear.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.similar_titles_include_external ?? true}
            disabled={
              !appSettings ||
              updateAppSettings.isPending ||
              !(appSettings?.similar_titles_enabled ?? true)
            }
            onChange={(e) =>
              updateAppSettings.mutate({
                similar_titles_include_external: e.target.checked,
              })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm">
          <span className="text-gray-700 dark:text-gray-300">
            Number of titles to show
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              How many similar titles to fetch and display (1–40).
            </span>
          </span>
          <input
            type="number"
            min={1}
            max={40}
            value={appSettings?.similar_titles_count ?? 12}
            disabled={
              !appSettings ||
              updateAppSettings.isPending ||
              !(appSettings?.similar_titles_enabled ?? true)
            }
            onChange={(e) => {
              const next = Number(e.target.value)
              if (!Number.isFinite(next)) return
              updateAppSettings.mutate({
                similar_titles_count: Math.min(40, Math.max(1, Math.round(next))),
              })
            }}
            className="w-16 shrink-0 border rounded px-2 py-1 text-sm border-gray-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          />
        </label>
      </Card>

      {/* Dashboard — only settings that affect the Dashboard page itself */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Dashboard</h2>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Show adult content
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Adult-flagged shows and episodes are always tracked; this only controls whether
              they appear in the dashboard&apos;s recently-added carousels.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.show_adult_content ?? false}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ show_adult_content: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Recently added episodes
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show the &quot;Recently Added Episodes&quot; carousel on the dashboard.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.recent_episodes_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ recent_episodes_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Recently added movies
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show the &quot;Recently Added Movies&quot; carousel on the dashboard.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.recent_movies_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ recent_movies_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Uniform episode artwork
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              In the &quot;Recently Added Episodes&quot; carousel, always use the show poster
              instead of the episode still, so every card has the same shape. Episodes
              without a still already fall back to the poster.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.recent_episodes_prefer_posters ?? false}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ recent_episodes_prefer_posters: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
      </Card>

      {/* Optional Pages — whole-page on/off switches, unrelated to Dashboard content */}
      <Card padding="md" className="space-y-3">
        <h2 className="font-semibold dark:text-gray-100">Optional Pages</h2>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Dashboard
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show the dashboard page and its nav link.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.dashboard_page_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ dashboard_page_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Calendar
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show the airing calendar page and its nav link.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.calendar_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ calendar_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
        <label className="flex items-center justify-between gap-3 text-sm cursor-pointer">
          <span className="text-gray-700 dark:text-gray-300">
            Discover
            <span className="block text-xs text-gray-400 dark:text-gray-500 font-normal">
              Show the discover page and its nav link.
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            checked={appSettings?.discover_enabled ?? true}
            disabled={!appSettings || updateAppSettings.isPending}
            onChange={(e) =>
              updateAppSettings.mutate({ discover_enabled: e.target.checked })
            }
            className="h-4 w-4 shrink-0 accent-[var(--color-ocean-600)]"
          />
        </label>
      </Card>
    </div>
  )
}
