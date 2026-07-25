import clsx from 'clsx'
import type { ReactNode } from 'react'

export type CardPadding = 'none' | 'sm' | 'md' | 'lg'

interface Props {
  padding?: CardPadding
  className?: string
  children: ReactNode
}

const PADDING: Record<CardPadding, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
}

export function Card({ padding = 'none', className, children }: Props) {
  return <div className={clsx('card', PADDING[padding], className)}>{children}</div>
}
