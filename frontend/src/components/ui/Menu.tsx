import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Button } from '@/components/ui/Button'
import type { ButtonSize, ButtonTone, ButtonVariant } from '@/components/ui/Button'

export interface MenuItem {
  label: string
  onSelect: () => void
  disabled?: boolean
}

interface Props {
  /** Trigger text; also names the menu for assistive tech. */
  label: string
  items: MenuItem[]
  variant?: ButtonVariant
  tone?: ButtonTone
  size?: ButtonSize
  /** Applied to the trigger button, so it can match its neighbours' width. */
  className?: string
}

/**
 * A small action menu (WAI-ARIA menu button pattern): a trigger that opens a
 * list of actions. Arrow keys / Home / End move between enabled items, Escape
 * closes and returns focus to the trigger, and clicking outside or tabbing
 * away closes it. Exists to fold the less common actions into one control
 * where a column of buttons would be cluttered.
 */
export function Menu({ label, items, variant = 'secondary', tone, size = 'sm', className }: Props) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([])

  const enabled = items.map((item, i) => (item.disabled ? -1 : i)).filter((i) => i >= 0)

  function focusItem(index: number | undefined) {
    if (index !== undefined) itemRefs.current[index]?.focus()
  }

  // Focus the first enabled item as the menu opens, per the menu button pattern.
  useEffect(() => {
    if (open) focusItem(enabled[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  function move(delta: 1 | -1) {
    if (enabled.length === 0) return
    const current = enabled.indexOf(itemRefs.current.findIndex((el) => el === document.activeElement))
    const next = current === -1 ? 0 : (current + delta + enabled.length) % enabled.length
    focusItem(enabled[next])
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        move(1)
        break
      case 'ArrowUp':
        event.preventDefault()
        move(-1)
        break
      case 'Home':
        event.preventDefault()
        focusItem(enabled[0])
        break
      case 'End':
        event.preventDefault()
        focusItem(enabled[enabled.length - 1])
        break
      case 'Escape':
        event.preventDefault()
        setOpen(false)
        triggerRef.current?.focus()
        break
      case 'Tab':
        setOpen(false)
        break
    }
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown' && !open) {
      event.preventDefault()
      setOpen(true)
    }
  }

  function select(item: MenuItem) {
    // Close first so a modal the action opens takes focus from a clean state.
    setOpen(false)
    item.onSelect()
  }

  return (
    <div ref={rootRef} className="relative">
      <Button
        ref={triggerRef}
        type="button"
        variant={variant}
        tone={tone}
        size={size}
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onTriggerKeyDown}
      >
        {label} <span aria-hidden="true">▾</span>
      </Button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          onKeyDown={onMenuKeyDown}
          className="absolute right-0 z-20 mt-1 min-w-[11rem] rounded border border-gray-200 bg-white py-1 shadow-lg dark:border-gray-700 dark:bg-gray-900"
        >
          {items.map((item, i) => (
            <button
              key={item.label}
              ref={(el) => {
                itemRefs.current[i] = el
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={item.disabled}
              onClick={() => select(item)}
              className={clsx(
                'block w-full whitespace-nowrap px-3 py-1.5 text-left text-xs text-gray-700 dark:text-gray-200',
                'hover:bg-gray-50 focus:bg-gray-100 focus:outline-none dark:hover:bg-gray-800 dark:focus:bg-gray-800',
                'disabled:cursor-not-allowed disabled:opacity-50',
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
