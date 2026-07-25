import { useEffect, useRef } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

// Stack of active trap ids, innermost (most recently mounted) last. Only the
// topmost trap responds to Tab/Escape, so a dialog opened on top of another
// dialog (e.g. a confirmation popup inside a modal) doesn't fight the one
// beneath it for keyboard handling — the outer trap resumes once the inner
// one unmounts.
const trapStack: object[] = []

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
  const idRef = useRef<object>({})

  // Capture the trigger during render — before autoFocus or any useEffect
  // fires — so we always restore to the element that opened the dialog.
  const triggerRef = useRef<Element | null>(
    typeof document !== 'undefined' ? document.activeElement : null,
  )

  // Restore focus to the trigger on unmount.
  useEffect(() => {
    const trigger = triggerRef.current
    return () => {
      if (trigger instanceof HTMLElement) trigger.focus()
    }
  }, [])

  // Register/unregister this trap on the shared stack.
  useEffect(() => {
    const id = idRef.current
    trapStack.push(id)
    return () => {
      const index = trapStack.indexOf(id)
      if (index !== -1) trapStack.splice(index, 1)
    }
  }, [])

  // Trap Tab/Shift+Tab within the dialog and handle Escape.
  useEffect(() => {
    const id = idRef.current

    function onKey(e: KeyboardEvent) {
      if (trapStack[trapStack.length - 1] !== id) return

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

      // If focus is outside the dialog entirely, pull it to the first element.
      if (!ref.current.contains(document.activeElement)) {
        e.preventDefault()
        first.focus()
        return
      }

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
