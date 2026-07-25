import clsx from 'clsx'
import type { ReactNode } from 'react'
import { useFocusTrap } from '@/hooks/useFocusTrap'

export type ModalTone = 'light' | 'dark'
export type ModalWidth = 'sm' | 'md' | 'lg' | 'xl' | '2xl'

interface Props {
  onClose: () => void
  tone?: ModalTone
  maxWidth?: ModalWidth
  role?: 'dialog' | 'alertdialog'
  labelledBy?: string
  describedBy?: string
  className?: string
  children: ReactNode
}

const MAX_WIDTH: Record<ModalWidth, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
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
  className,
  children,
}: Props) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose)

  return (
    <div className="overlay" role={role} aria-modal="true" aria-labelledby={labelledBy} aria-describedby={describedBy}>
      <div ref={dialogRef} className={clsx('w-full', MAX_WIDTH[maxWidth], PANEL_TONE[tone], className)}>
        {children}
      </div>
    </div>
  )
}
