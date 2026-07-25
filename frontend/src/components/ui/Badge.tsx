import clsx from 'clsx'
import type { ReactNode } from 'react'

interface Props {
  /** Tailwind background/text (and optional hover) classes for this badge's color. */
  color: string
  children: ReactNode
  onClick?: () => void
  title?: string
  className?: string
}

/**
 * Static or clickable badge/pill. Renders a `<button>` when `onClick` is
 * given (the click-to-reveal-a-dropdown pattern used for status/queue
 * pills), otherwise a plain `<span>`.
 */
export function Badge({ color, children, onClick, title, className }: Props) {
  const classes = clsx('badge', color, onClick && 'hover:opacity-80', className)

  if (onClick) {
    return (
      <button onClick={onClick} title={title} className={classes}>
        {children}
      </button>
    )
  }

  return (
    <span title={title} className={classes}>
      {children}
    </span>
  )
}
