import { useEffect, useRef } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Traps keyboard focus within a dialog element and restores focus on unmount.
 *
 * Returns a ref to attach to the dialog's root element. The caller is
 * responsible for wiring Escape to the onClose callback.
 */
export function useFocusTrap<T extends HTMLElement>(onClose?: () => void) {
  const ref = useRef<T>(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  // Restore focus to the element that was active before the dialog opened.
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null
    return () => {
      trigger?.focus()
    }
  }, [])

  // Trap Tab/Shift+Tab within the dialog and handle Escape.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onCloseRef.current?.()
        return
      }

      if (e.key !== 'Tab' || !ref.current) return

      const focusable = Array.from(
        ref.current.querySelectorAll<HTMLElement>(FOCUSABLE),
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

  return ref
}
