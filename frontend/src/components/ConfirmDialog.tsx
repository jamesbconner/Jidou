import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'

interface Props {
  title: string
  description: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  danger?: boolean
}

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function ConfirmDialog({
  title,
  description,
  confirmLabel = 'Confirm',
  onConfirm,
  onCancel,
  danger = false,
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const onCancelRef = useRef(onCancel)
  const [fired, setFired] = useState(false)

  // Keep ref current without triggering effects.
  onCancelRef.current = onCancel

  // Focus Cancel once on mount only.
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])

  // Trap focus within the dialog + handle Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onCancelRef.current()
        return
      }

      if (e.key !== 'Tab' || !dialogRef.current) return

      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      )
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

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
