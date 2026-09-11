import type { ReactNode } from 'react'
import type { ShowRead } from '@/types/api'
import type { BannerStyle } from '@/hooks/useBannerStyle'

const TMDB_BACKDROP = '/api/images/w1280'

interface Props {
  show: ShowRead
  /** Chosen banner treatment (Settings → Appearance). */
  style: BannerStyle
  /** Fully-qualified poster URL, or null when the show has no poster. */
  posterSrc: string | null
  /** External TMDB page URL for the metadata line. */
  tmdbUrl: string
  /** Watchlist / watched / tracking controls, built by the page. */
  primaryActions: ReactNode
  /** Overview, progress bar and the tracked/linked summary line. */
  secondaryInfo: ReactNode
  /** Remove / RSS / Fix Match / … stack, built by the page. */
  maintenanceActions: ReactNode
}

/**
 * Header region of the show detail page. Renders the poster, title, metadata and
 * the page-supplied action slots in one of four arrangements:
 *
 * - `hero`      — full-width backdrop with a dark gradient; poster, title and
 *   (frosted) primary actions overlaid, everything else below.
 * - `contained` — the whole 16:9 backdrop always visible (blurred fill + sharp
 *   letterbox); title and frosted actions overlaid on the bottom.
 * - `full`      — the whole uncropped backdrop, then the plain header beneath it.
 * - `none`      — no backdrop; the plain header only.
 *
 * A show without a `backdrop_path` always falls back to the plain header.
 */
export function ShowDetailHeader({
  show,
  style,
  posterSrc,
  tmdbUrl,
  primaryActions,
  secondaryInfo,
  maintenanceActions,
}: Props) {
  const backdropImg = (className: string) => (
    <img src={`${TMDB_BACKDROP}${show.backdrop_path}`} alt="" loading="lazy" className={className} />
  )

  // Year · type · ★ rating · TMDB link · content-type chip. `onImage` picks
  // light colours for overlaying on a backdrop.
  const metaLine = (onImage: boolean) => (
    <p className={`text-sm mt-1 ${onImage ? 'text-white/80' : 'text-gray-500 dark:text-gray-400'}`}>
      {show.release_date?.slice(0, 4)}
      {show.release_date && ' · '}
      {show.media_type}
      {show.vote_average != null && ` · ★ ${show.vote_average.toFixed(1)}`}
      {' · '}
      <a
        href={tmdbUrl}
        target="_blank"
        rel="noreferrer"
        className={`hover:underline ${
          onImage
            ? 'text-[var(--color-ocean-300)]'
            : 'text-[var(--color-ocean-600)] dark:text-[var(--color-ocean-400)]'
        }`}
      >
        TMDB #{show.tmdb_id}
      </a>
      {show.content_type && (
        <span
          className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
            onImage
              ? 'bg-white/15 text-white'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'
          }`}
        >
          {show.content_type}
        </span>
      )}
    </p>
  )

  // Frosted restyle of primaryActions for use over imagery.
  const overlayActions = (
    <div className="mt-2 [&_button]:!border-white/30 [&_button]:!bg-white/10 [&_button]:!text-white [&_button]:backdrop-blur-sm [&_button:hover]:!bg-white/20">
      {primaryActions}
    </div>
  )

  const backdropBox = (
    boxClassName: string,
    opts: { imgClassName?: string; scrim?: ReactNode; children?: ReactNode } = {},
  ) => (
    <div className={`relative overflow-hidden ${boxClassName}`}>
      {backdropImg(`absolute inset-0 h-full w-full ${opts.imgClassName ?? 'object-cover'}`)}
      {opts.scrim}
      {opts.children != null && <div className="relative">{opts.children}</div>}
    </div>
  )

  const infoBelow = (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">{secondaryInfo}</div>
      {maintenanceActions}
    </div>
  )

  const plainHeader = (
    <div className="flex gap-6">
      {posterSrc && (
        <img
          src={posterSrc}
          alt={show.title}
          className="w-48 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-bold dark:text-gray-100">{show.title}</h1>
            {metaLine(false)}
            {primaryActions}
            {secondaryInfo}
          </div>
          {maintenanceActions}
        </div>
      </div>
    </div>
  )

  if (!show.backdrop_path || style === 'none') return plainHeader

  if (style === 'hero') {
    return (
      <div className="space-y-6">
        {backdropBox('rounded-xl min-h-[22rem]', {
          scrim: (
            <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/45 to-black/10" />
          ),
          children: (
            <div className="flex gap-6 p-6 pt-40 sm:pt-56">
              {posterSrc && (
                <img
                  src={posterSrc}
                  alt={show.title}
                  className="w-32 sm:w-44 aspect-[2/3] self-end rounded-lg object-cover shadow-2xl ring-1 ring-black/20"
                />
              )}
              <div className="flex-1 min-w-0 self-end">
                <h1 className="text-3xl font-bold text-white drop-shadow">{show.title}</h1>
                {metaLine(true)}
                {overlayActions}
              </div>
            </div>
          ),
        })}
        {infoBelow}
      </div>
    )
  }

  if (style === 'full') {
    return (
      <div className="space-y-6">
        {backdropBox('-mx-6 aspect-video bg-black', { imgClassName: 'object-contain' })}
        {plainHeader}
      </div>
    )
  }

  // 'contained' — whole 16:9 frame always visible (blurred fill + sharp
  // letterbox), in a rounded card that echoes the poster's corners. The caption
  // block sits in normal flow (not absolutely positioned), so a tall wrapped
  // action row grows the card instead of being clipped by overflow-hidden on
  // narrow viewports.
  return (
    <div className="space-y-6">
      <div className="relative -mx-6 overflow-hidden rounded-lg bg-black">
        <div className="relative aspect-video">
          {backdropImg('absolute inset-0 h-full w-full object-cover blur-2xl scale-110 opacity-50')}
          {backdropImg('absolute inset-0 h-full w-full object-contain')}
          <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/80 to-transparent" />
        </div>
        <div className="relative -mt-16 bg-gradient-to-t from-black via-black/95 to-black/70 px-6 pt-4 pb-6">
          <h1 className="text-2xl sm:text-3xl font-bold text-white drop-shadow">{show.title}</h1>
          {metaLine(true)}
          {overlayActions}
        </div>
      </div>
      <div className="flex gap-6">
        {posterSrc && (
          <img
            src={posterSrc}
            alt={show.title}
            className="w-44 aspect-[2/3] self-start rounded-lg object-cover hidden md:block"
          />
        )}
        <div className="flex-1 min-w-0">{infoBelow}</div>
      </div>
    </div>
  )
}
