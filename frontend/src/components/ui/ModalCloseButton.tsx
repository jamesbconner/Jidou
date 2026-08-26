import clsx from 'clsx'
import { useContext } from 'react'
import { ModalToneContext } from '@/components/ui/Modal'

export type ModalCloseButtonTone = 'light' | 'dark'

interface Props {
  onClose: () => void
  /** Defaults to the enclosing Modal's tone, then falls back to 'light'. */
  tone?: ModalCloseButtonTone
  /**
   * Reproduces the ~8px real gap some headers used to get from a plain
   * `ml-2` on the old bare button (e.g. next to a `truncate`d title, where
   * the gap is load-bearing for how much width the title gets before
   * eliding). Left unset, `-m-2`'s margin-left and the button's own
   * `p-2` cancel out net-zero, same as before this component existed.
   *
   * This can't be done by passing `ml-2` via `className` instead: both it
   * and the base `-m-2` set the same `margin-left` property, and whichever
   * one Tailwind happens to emit later in the generated stylesheet wins
   * regardless of class order in the JSX — in practice `ml-2` won, leaving
   * margin-left at +8px on top of the button's own +8px padding, doubling
   * the gap instead of preserving it. Omitting `-ml-2` here for this case
   * sidesteps the conflict entirely: with no competing class, margin-left
   * is simply unset (0), so it's the padding alone that reproduces the
   * original gap while still growing the hit area.
   */
  leftGap?: boolean
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
export function ModalCloseButton({ onClose, tone, leftGap, className }: Props) {
  const modalTone = useContext(ModalToneContext)
  const resolvedTone = tone ?? modalTone ?? 'light'
  return (
    <button
      type="button"
      onClick={onClose}
      aria-label="Close"
      className={clsx(
        leftGap ? '-mt-2 -mr-2 -mb-2 p-2' : '-m-2 p-2',
        'shrink-0 leading-none text-lg transition-colors',
        TONE[resolvedTone],
        className,
      )}
    >
      ✕
    </button>
  )
}
