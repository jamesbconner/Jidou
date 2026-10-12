import type { EpisodeList, FileRead, RssSubscriptionRead } from '@/types/api'

/**
 * Which ShowDetail modal is open, if any.
 *
 * Replaces twelve independent open/closed flags (and three "selected item"
 * states) with one discriminated union: at most one modal exists at a time, the
 * payload a modal needs travels with its `kind`, and adding a variant forces
 * every `switch` over `kind` to handle it (see the `never` check in
 * `ShowDetailModals`).
 */
export type ShowDetailModal =
  | { kind: 'rematch' }
  | { kind: 'path' }
  | { kind: 'contentType' }
  | { kind: 'aliases' }
  | { kind: 'image' }
  | { kind: 'deleteConfirm' }
  | { kind: 'scanLocalFiles' }
  | { kind: 'episodeGroups' }
  | { kind: 'scanLocalMovieFile' }
  | { kind: 'fixMovieFile' }
  | { kind: 'fileRematch'; file: FileRead }
  | { kind: 'fileFixEps'; file: FileRead }
  | { kind: 'assignImport'; episode: EpisodeList }
  | { kind: 'linkFile'; episode: EpisodeList }
  | { kind: 'rssSubscription'; subscription: RssSubscriptionRead }
