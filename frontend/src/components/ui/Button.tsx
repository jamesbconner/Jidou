import clsx from 'clsx'
import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export type ButtonTone = 'light' | 'dark'
export type ButtonSize = 'sm' | 'md'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  tone?: ButtonTone
  size?: ButtonSize
}

const SIZE: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
}

// Preserves the exact colors already in use per tone — this is a
// deduplication pass, not a re-brand of the existing blue/indigo split.
const VARIANT: Record<ButtonTone, Record<ButtonVariant, string>> = {
  light: {
    primary: 'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'border border-gray-300 text-gray-700 hover:bg-gray-50',
    danger: 'border border-red-300 text-red-600 hover:bg-red-50',
    ghost: 'text-gray-600 hover:bg-gray-50',
  },
  dark: {
    primary: 'bg-indigo-600 text-white hover:bg-indigo-500',
    secondary: 'border border-zinc-600 text-zinc-300 hover:bg-zinc-700',
    danger: 'bg-red-600 text-white hover:bg-red-500',
    ghost: 'text-zinc-400 hover:text-zinc-200',
  },
}

export function Button({ variant = 'secondary', tone = 'light', size = 'md', className, ...props }: Props) {
  return <button className={clsx('btn', SIZE[size], VARIANT[tone][variant], className)} {...props} />
}
