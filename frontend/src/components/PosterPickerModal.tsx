import { useState } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { useShowPosters, usePatchShow } from '@/hooks/useShows'
import type { ShowRead } from '@/types/api'

const TMDB_THUMB = '/api/images/w185'

interface Props {
  show: ShowRead
  onClose: () => void
}

type Target = 'list' | 'detail'

export function PosterPickerModal({ show, onClose }: Props) {
  const { data: posters, isLoading, isError } = useShowPosters(show.id)
  const patchShow = usePatchShow()
  const [pending, setPending] = useState<{ filePath: string; target: Target } | null>(null)

  const activeListPath = show.list_poster_path ?? show.poster_path
  const activeDetailPath = show.detail_poster_path ?? show.poster_path

  function select(filePath: string, target: Target) {
    setPending({ filePath, target })
    const patch = target === 'list' ? { list_poster_path: filePath } : { detail_poster_path: filePath }
    patchShow.mutate(
      { id: show.id, patch },
      { onSettled: () => setPending(null) },
    )
  }

  return (
    <Modal
      onClose={onClose}
      tone="light"
      maxWidth="3xl"
      ariaLabel={`Choose poster for ${show.title}`}
      className="flex flex-col max-h-[90vh]"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b">
        <h2 className="font-semibold text-gray-900 dark:text-gray-100 truncate">Choose Poster — {show.title}</h2>
        <button onClick={onClose} className="ml-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" aria-label="Close">
          ✕
        </button>
      </div>

      {/* Body */}
      <div className="overflow-y-auto flex-1 px-5 py-4">
        {isLoading && <p className="text-sm text-gray-500 dark:text-gray-400">Loading posters…</p>}
        {isError && (
          <p className="text-sm text-red-600 dark:text-red-400">Failed to load posters — check server logs.</p>
        )}
        {posters && posters.length === 0 && (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">No alternate posters available for this show.</p>
        )}
        {posters && posters.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
            {posters.map((p) => {
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
                          <span className="bg-blue-500 text-white text-[10px] font-medium px-1.5 py-0.5 rounded shadow">
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
                      onClick={() => select(p.file_path, 'list')}
                      disabled={isActiveList || (patchShow.isPending && isPendingThis)}
                      className="flex-1 text-xs border rounded px-1.5 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
                    >
                      {isPendingThis && pending?.target === 'list' ? '…' : 'Use for Shows'}
                    </button>
                    <button
                      onClick={() => select(p.file_path, 'detail')}
                      disabled={isActiveDetail || (patchShow.isPending && isPendingThis)}
                      className="flex-1 text-xs border rounded px-1.5 py-1 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 disabled:cursor-default"
                    >
                      {isPendingThis && pending?.target === 'detail' ? '…' : 'Use for Details'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
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
