import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useFocusTrap } from '@/hooks/useFocusTrap'

export type ModalTone = 'light' | 'dark'
export type ModalWidth = 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl'

interface Props {
  onClose: () => void
  tone?: ModalTone
  maxWidth?: ModalWidth
  role?: 'dialog' | 'alertdialog'
  labelledBy?: string
  describedBy?: string
  ariaLabel?: string
  /** Extra classes for the backdrop itself — e.g. a higher z-index for a modal stacked above another. */
  overlayClassName?: string
  /** Close when the backdrop (not the panel) is clicked. Default false. */
  closeOnBackdropClick?: boolean
  className?: string
  children: ReactNode
}

const MAX_WIDTH: Record<ModalWidth, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
  '3xl': 'max-w-3xl',
}

const PANEL_TONE: Record<ModalTone, string> = {
  light: 'panel-light',
  dark: 'panel-dark',
}

/**
 * Overlay + centered panel shell shared by every modal in the app.
 *
 * Owns focus trapping and Escape-to-close via `useFocusTrap` (the same hook
 * several modals already wired up individually) so every modal gets the
 * same keyboard behavior for free once migrated.
 */
export function Modal({
  onClose,
  tone = 'light',
  maxWidth = 'lg',
  role = 'dialog',
  labelledBy,
  describedBy,
  ariaLabel,
  overlayClassName,
  closeOnBackdropClick = false,
  className,
  children,
}: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)

  return (
    <div
      className={clsx('overlay', overlayClassName)}
      role={role}
      aria-modal="true"
      aria-label={ariaLabel}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      onClick={closeOnBackdropClick ? onClose : undefined}
    >
      <div
        ref={dialogRef}
        className={clsx('w-full', MAX_WIDTH[maxWidth], PANEL_TONE[tone], className)}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  )
}
