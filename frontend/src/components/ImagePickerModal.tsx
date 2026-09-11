import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { ModalCloseButton } from '@/components/ui/ModalCloseButton'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useShowPosters, useShowBackdrops, usePatchShow } from '@/hooks/useShows'
import type { ShowRead, ShowPatch, PosterOption } from '@/types/api'

const TMDB_THUMB = '/api/images/w185'
const TMDB_BACKDROP_THUMB = '/api/images/w780'

interface Props {
  show: ShowRead
  onClose: () => void
}

type Tab = 'poster' | 'banner'
type PosterTarget = 'list' | 'detail'

/** Which thumbnail+action is mid-mutation, shared across both tabs since only one grid is interactive at a time. */
interface Pending {
  filePath: string
  key: PosterTarget | 'banner'
}

export function ImagePickerModal({ show, onClose }: Props) {
  const [tab, setTab] = useState<Tab>('poster')
  const patchShow = usePatchShow()
  const [pending, setPending] = useState<Pending | null>(null)

  const { data: posters, isLoading: postersLoading, isError: postersError } = useShowPosters(
    show.id,
    { enabled: tab === 'poster' },
  )
  const { data: backdrops, isLoading: backdropsLoading, isError: backdropsError } =
    useShowBackdrops(show.id, { enabled: tab === 'banner' })

  function select(filePath: string, key: Pending['key'], patch: ShowPatch) {
    setPending({ filePath, key })
    patchShow.mutate({ id: show.id, patch }, { onSettled: () => setPending(null) })
  }

  return (
    <Modal
      onClose={onClose}
      tone="light"
      maxWidth="3xl"
      ariaLabel={`Choose images for ${show.title}`}
      className="flex flex-col max-h-[90vh]"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b gap-4">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 truncate">
          Change Images — {show.title}
        </h2>
        <div className="flex items-center gap-3 shrink-0">
          <SegmentedControl<Tab>
            aria-label="Image type"
            value={tab}
            onChange={setTab}
            options={[
              { value: 'poster', label: 'Poster' },
              { value: 'banner', label: 'Banner' },
            ]}
          />
          <ModalCloseButton onClose={onClose} leftGap />
        </div>
      </div>

      {/* Body */}
      <div className="overflow-y-auto flex-1 px-5 py-4">
        {tab === 'poster' ? (
          <PosterGrid
            show={show}
            posters={posters}
            isLoading={postersLoading}
            isError={postersError}
            pending={pending}
            isPatchPending={patchShow.isPending}
            onSelect={select}
          />
        ) : (
          <BannerGrid
            show={show}
            backdrops={backdrops}
            isLoading={backdropsLoading}
            isError={backdropsError}
            pending={pending}
            isPatchPending={patchShow.isPending}
            onSelect={select}
          />
        )}
      </div>

      {/* Footer */}
      <div className="flex justify-end gap-2 px-5 py-3 border-t">
        <Button onClick={onClose} variant="primary" tone="light" size="md">
          Done
        </Button>
      </div>
    </Modal>
  )
}

interface GridProps {
  show: ShowRead
  isLoading: boolean
  isError: boolean
  pending: Pending | null
  isPatchPending: boolean
  onSelect: (filePath: string, key: Pending['key'], patch: ShowPatch) => void
}

function PosterGrid({
  show,
  posters,
  isLoading,
  isError,
  pending,
  isPatchPending,
  onSelect,
}: GridProps & { posters: PosterOption[] | undefined }) {
  const activeListPath = show.list_poster_path ?? show.poster_path
  const activeDetailPath = show.detail_poster_path ?? show.poster_path

  if (isLoading) return <p className="text-sm text-gray-500 dark:text-gray-400">Loading posters…</p>
  if (isError)
    return (
      <p className="text-sm text-red-600 dark:text-red-400">Failed to load posters — check server logs.</p>
    )
  if (posters && posters.length === 0)
    return (
      <p className="text-sm text-gray-400 dark:text-gray-500 italic">
        No alternate posters available for this show.
      </p>
    )

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
      {posters?.map((p) => {
        const isActiveList = p.file_path === activeListPath
        const isActiveDetail = p.file_path === activeDetailPath
        const isPendingThis = pending?.filePath === p.file_path

        return (
          <div key={p.file_path} className="space-y-1.5">
            <div className="relative">
              <img
                src={`${TMDB_THUMB}${p.file_path}`}
                alt={`${show.title} poster option`}
                className="w-full aspect-[2/3] object-cover rounded-lg border dark:border-gray-700"
                loading="lazy"
              />
              {(isActiveList || isActiveDetail) && (
                <div className="absolute top-1 left-1 flex flex-col gap-1">
                  {isActiveList && (
                    <span className="bg-[var(--color-ocean-500)] text-white text-[10px] font-medium px-1.5 py-0.5 rounded shadow">
                      Shows page
                    </span>
                  )}
                  {isActiveDetail && (
                    <span className="bg-green-500 text-white text-[10px] font-medium px-1.5 py-0.5 rounded shadow">
                      Details page
                    </span>
                  )}
                </div>
              )}
            </div>
            <div className="flex gap-1">
              <button
                onClick={() => onSelect(p.file_path, 'list', { list_poster_path: p.file_path })}
                disabled={isActiveList || (isPatchPending && isPendingThis)}
                className="flex-1 text-xs border rounded px-1.5 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
              >
                {isPendingThis && pending?.key === 'list' ? '…' : 'Use for Shows'}
              </button>
              <button
                onClick={() => onSelect(p.file_path, 'detail', { detail_poster_path: p.file_path })}
                disabled={isActiveDetail || (isPatchPending && isPendingThis)}
                className="flex-1 text-xs border rounded px-1.5 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
              >
                {isPendingThis && pending?.key === 'detail' ? '…' : 'Use for Details'}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function BannerGrid({
  show,
  backdrops,
  isLoading,
  isError,
  pending,
  isPatchPending,
  onSelect,
}: GridProps & { backdrops: PosterOption[] | undefined }) {
  const activeBannerPath = show.banner_path ?? show.backdrop_path

  if (isLoading) return <p className="text-sm text-gray-500 dark:text-gray-400">Loading banners…</p>
  if (isError)
    return (
      <p className="text-sm text-red-600 dark:text-red-400">Failed to load banners — check server logs.</p>
    )
  if (backdrops && backdrops.length === 0)
    return (
      <p className="text-sm text-gray-400 dark:text-gray-500 italic">
        No alternate banners available for this show.
      </p>
    )

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {backdrops?.map((b) => {
        const isActive = b.file_path === activeBannerPath
        const isPendingThis = pending?.filePath === b.file_path && pending.key === 'banner'

        return (
          <div key={b.file_path} className="space-y-1.5">
            <div className="relative">
              <img
                src={`${TMDB_BACKDROP_THUMB}${b.file_path}`}
                alt={`${show.title} banner option`}
                className="w-full aspect-video object-cover rounded-lg border dark:border-gray-700"
                loading="lazy"
              />
              {isActive && (
                <span className="absolute top-1 left-1 bg-[var(--color-ocean-500)] text-white text-[10px] font-medium px-1.5 py-0.5 rounded shadow">
                  Current banner
                </span>
              )}
            </div>
            <button
              onClick={() => onSelect(b.file_path, 'banner', { banner_path: b.file_path })}
              disabled={isActive || (isPatchPending && isPendingThis)}
              className="w-full text-xs border rounded px-1.5 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
            >
              {isPendingThis ? '…' : 'Use as banner'}
            </button>
          </div>
        )
      })}
    </div>
  )
}
