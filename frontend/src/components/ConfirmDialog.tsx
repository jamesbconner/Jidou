import { useEffect, useRef } from 'react'
import clsx from 'clsx'

interface Props {
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  danger?: boolean
}

export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirm',
  onConfirm,
  onCancel,
  danger = false,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    cancelRef.current?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-desc"
    >
      <div className="w-full max-w-sm rounded-lg bg-zinc-900 shadow-xl">
        <div className="px-5 py-4 space-y-2">
          <h2 id="confirm-dialog-title" className="text-sm font-semibold text-zinc-100">
            {title}
          </h2>
          <p id="confirm-dialog-desc" className="text-sm text-zinc-400">
            {description}
          </p>
        </div>
        <div className="px-5 py-3 border-t border-zinc-700 flex justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={clsx(
              'px-3 py-1.5 text-xs rounded text-white transition-colors',
              danger
                ? 'bg-red-600 hover:bg-red-500'
                : 'bg-indigo-600 hover:bg-indigo-500',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
