import { useLocalStorageState } from './useLocalStorage'

export const BANNER_STYLES = ['hero', 'full', 'none'] as const

/** Backdrop treatment shown at the top of the show detail page. */
export type BannerStyle = (typeof BANNER_STYLES)[number]

export const DEFAULT_BANNER_STYLE: BannerStyle = 'hero'

const STORAGE_KEY = 'jidou.bannerStyle'

function normalize(value: unknown): BannerStyle {
  return (BANNER_STYLES as readonly unknown[]).includes(value)
    ? (value as BannerStyle)
    : DEFAULT_BANNER_STYLE
}

/**
 * Browser-local preference for the show detail page's banner style.
 *
 * Persisted to localStorage like the colour-scheme preference (`stores/theme`);
 * it is intentionally not synced to the backend. Returns a `useState`-style
 * tuple; the stored value is normalised on read so a stale or hand-edited key
 * can never yield an unknown style.
 */
export function useBannerStyle() {
  const [raw, setRaw] = useLocalStorageState<BannerStyle>(STORAGE_KEY, DEFAULT_BANNER_STYLE)
  return [normalize(raw), setRaw] as const
}
