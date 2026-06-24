import type { ShowList } from '@/types/api'

export interface DqCheck {
  key: string
  label: string
  description: string
  test: (s: ShowList) => boolean
}

export const DQ_CHECKS: DqCheck[] = [
  {
    key: 'no_path',
    label: 'No local path',
    description: 'Route task cannot place files without a destination path.',
    test: (s) => s.local_path == null,
  },
  {
    key: 'no_content_type',
    label: 'Content type unset',
    description: 'Routing category (Anime / TV / Movie) is required for correct folder placement.',
    test: (s) => s.content_type == null,
  },
  {
    key: 'no_local_episodes',
    label: 'Episodes not synced',
    description:
      'No episode records in the local database — run Sync Episodes from the show detail page.',
    test: (s) => s.media_type !== 'movie' && s.episode_count === 0,
  },
  {
    key: 'orphan',
    label: 'No files tracked',
    description:
      'TV or anime show with no episodes and no downloaded files — nothing from either the download or import pipeline. May be a stale or accidental library entry.',
    test: (s) =>
      s.media_type !== 'movie' &&
      (s.media_type === 'tv' || s.content_type === 'anime') &&
      s.episode_count === 0 &&
      s.matched_file_count === 0,
  },
]
