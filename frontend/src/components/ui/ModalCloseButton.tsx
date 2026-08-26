import clsx from 'clsx'
import { useContext } from 'react'
import { ModalToneContext } from '@/components/ui/Modal'

export type ModalCloseButtonTone = 'light' | 'dark'

interface Props {
  onClose: () => void
  /** Defaults to the enclosing Modal's tone, then falls back to 'light'. */
  tone?: ModalCloseButtonTone
  className?: string
}

const TONE: Record<ModalCloseButtonTone, string> = {
  light: 'text-gray-400 hover:text-gray-700 dark:hover:text-gray-200',
  dark: 'text-zinc-400 hover:text-zinc-200',
}

/**
 * The '✕' button every modal header uses to close. Padding is negated with a
 * matching negative margin so the glyph keeps its current visual position
 * while the actual hit area grows to ~34x34px — comfortably past the 24x24
 * minimum touch target (WCAG 2.5.8) that the bare glyph alone didn't meet.
 */
export function ModalCloseButton({ onClose, tone, className }: Props) {
  const modalTone = useContext(ModalToneContext)
  const resolvedTone = tone ?? modalTone ?? 'light'
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close"
      className={clsx(
        '-m-2 p-2 shrink-0 leading-none text-lg transition-colors',
        TONE[resolvedTone],
        className,
      )}
    >
      ✕
    </button>
  )
}
