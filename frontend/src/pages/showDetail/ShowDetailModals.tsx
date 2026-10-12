import { RematchModal } from '@/components/RematchModal'
import { FixEpisodeModal } from '@/components/FixEpisodeModal'
import { AssignImportModal } from '@/components/AssignImportModal'
import { LinkFileModal } from '@/components/LinkFileModal'
import { ScanLocalFilesModal } from '@/components/ScanLocalFilesModal'
import { ScanLocalMovieFileModal } from '@/components/ScanLocalMovieFileModal'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { AliasModal } from '@/components/AliasModal'
import { ImagePickerModal } from '@/components/ImagePickerModal'
import { SubscriptionEditModal } from '@/components/SubscriptionEditModal'
import { ShowRematchModal } from '@/components/ShowRematchModal'
import { EpisodeGroupPickerModal } from '@/components/EpisodeGroupPickerModal'
import { ContentTypeModal } from '@/components/ContentTypeModal'
import { EditPathModal } from '@/components/EditPathModal'
import type { ShowDetailModal } from '@/pages/showDetail/modalState'
import type { ContentType, RssFeedRead, ShowRead } from '@/types/api'

interface ShowDetailModalsProps {
  show: ShowRead
  modal: ShowDetailModal | null
  onClose: () => void
  rssFeeds: RssFeedRead[]
  onConfirmDelete: () => void
  onSavePath: (path: string | null) => void
  isSavingPath: boolean
  onSaveContentType: (value: ContentType | null) => Promise<void>
  onResetContentType: () => void
  isSavingContentType: boolean
  contentTypeError: Error | null
}

/**
 * Renders the single ShowDetail modal selected by `modal`, or nothing.
 *
 * Purely presentational: every page mutation and its pending/error state stays
 * in ShowDetail (it outlives a modal being closed) and arrives here as props.
 * Each modal component still owns its own queries, so they mount and fetch
 * exactly when they did before this component existed.
 */
export function ShowDetailModals({
  show,
  modal,
  onClose,
  rssFeeds,
  onConfirmDelete,
  onSavePath,
  isSavingPath,
  onSaveContentType,
  onResetContentType,
  isSavingContentType,
  contentTypeError,
}: ShowDetailModalsProps) {
  if (!modal) return null
  const showId = show.id

  switch (modal.kind) {
    case 'deleteConfirm':
      return (
        <ConfirmDialog
          title="Remove show?"
          description={`Remove "${show.title}" and all its episode data? This cannot be undone.`}
          confirmLabel="Remove"
          danger
          onConfirm={onConfirmDelete}
          onCancel={onClose}
        />
      )
    case 'path':
      return (
        <EditPathModal
          current={show.local_path ?? null}
          onSave={onSavePath}
          onClose={onClose}
          isPending={isSavingPath}
        />
      )
    case 'rematch':
      return (
        <ShowRematchModal
          key={showId}
          showId={showId}
          currentTmdbId={show.tmdb_id}
          onClose={onClose}
        />
      )
    case 'rssSubscription':
      return <SubscriptionEditModal sub={modal.subscription} feeds={rssFeeds} onClose={onClose} />
    case 'contentType':
      return (
        <ContentTypeModal
          key={showId}
          current={show.content_type ?? null}
          onSave={onSaveContentType}
          onClose={() => {
            onClose()
            onResetContentType()
          }}
          isPending={isSavingContentType}
          error={contentTypeError}
        />
      )
    case 'aliases':
      return <AliasModal show={show} onClose={onClose} />
    case 'image':
      return <ImagePickerModal show={show} onClose={onClose} />
    case 'fileRematch':
      return <RematchModal file={modal.file} onClose={onClose} />
    case 'fileFixEps':
      return <FixEpisodeModal file={modal.file} onClose={onClose} />
    case 'assignImport':
      return <AssignImportModal showId={showId} episode={modal.episode} onClose={onClose} />
    case 'linkFile':
      return (
        <LinkFileModal
          showId={showId}
          showLocalPath={show.local_path ?? null}
          episode={modal.episode}
          onClose={onClose}
        />
      )
    case 'scanLocalFiles':
      return <ScanLocalFilesModal showId={showId} onClose={onClose} />
    case 'episodeGroups':
      return <EpisodeGroupPickerModal show={show} onClose={onClose} />
    case 'scanLocalMovieFile':
      return <ScanLocalMovieFileModal showId={showId} onClose={onClose} />
    case 'fixMovieFile':
      return <ScanLocalMovieFileModal showId={showId} replace onClose={onClose} />
    default: {
      const unhandled: never = modal
      return unhandled
    }
  }
}
