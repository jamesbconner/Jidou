import { useRef, useState } from 'react'
import clsx from 'clsx'
import { useFocusTrap } from '@/hooks/useFocusTrap'

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
  const dialogRef = useFocusTrap<HTMLDivElement>(onCancel)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const [fired, setFired] = useState(false)

  // Focus Cancel on mount (useFocusTrap handles Escape + Tab trap).
  // Using a callback ref on the Cancel button keeps this in one place.

  function handleConfirm() {
    if (fired) return
    setFired(true)
    onConfirm()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-desc"
    >
      <div ref={dialogRef} className="w-full max-w-sm rounded-lg bg-zinc-900 shadow-xl">
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
            disabled={fired}
            autoFocus
            className="px-3 py-1.5 text-xs rounded border border-zinc-600 text-zinc-300 hover:bg-zinc-700 disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={fired}
            className={clsx(
              'px-3 py-1.5 text-xs rounded text-white transition-colors disabled:opacity-50',
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
