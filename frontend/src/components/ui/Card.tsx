import clsx from 'clsx'
import type { ReactNode } from 'react'

export type CardPadding = 'none' | 'sm' | 'md' | 'lg'

// Note: onClick/title are hand-declared here rather than spread from
// React.HTMLAttributes because only these two native attributes have callers
// today. If a third one-off attribute need shows up (onMouseEnter, aria-label,
// data-testid, etc.), switch to `...rest: React.HTMLAttributes<HTMLElement>`
// instead of adding a fourth bespoke field.
interface Props {
  as?: 'div' | 'section' | 'button'
  padding?: CardPadding
  className?: string
  onClick?: () => void
  title?: string
  children: ReactNode
}

const PADDING: Record<CardPadding, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
}

export function Card({ as: Tag = 'div', padding = 'none', className, onClick, title, children }: Props) {
  return (
    <Tag className={clsx('card', PADDING[padding], className)} onClick={onClick} title={title}>
      {children}
    </Tag>
  )
}
