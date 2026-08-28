import clsx from 'clsx'
import { useContext } from 'react'
import type { ButtonHTMLAttributes } from 'react'
import { ModalToneContext } from '@/components/ui/Modal'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'
export type ButtonTone = 'light' | 'dark'
export type ButtonSize = 'sm' | 'md'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  /** Defaults to the enclosing Modal's tone, then falls back to 'light'. */
  tone?: ButtonTone
  size?: ButtonSize
}

const SIZE: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
}

// Brand primary is verdant (pine green) and danger is ember (coral) in both
// tones, per the Stone & Pine palette. Secondary stays neutral gray/zinc —
// those scales already carry the palette via the --color-gray-* theme
// override, and panel-dark's zinc chrome is a deliberately separate
// always-dark look. verdant/ember are referenced via arbitrary-value syntax
// (bg-[var(--color-verdant-600)]) rather than the named form — see the note
// in index.css on why the named form silently fails to generate here.
const VARIANT: Record<ButtonTone, Record<ButtonVariant, string>> = {
  light: {
    primary: 'bg-[var(--color-verdant-600)] text-white hover:bg-[var(--color-verdant-700)]',
    secondary: 'border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800',
    danger:
      'border border-[var(--color-ember-300)] text-[var(--color-ember-600)] hover:bg-[var(--color-ember-50)] dark:border-[var(--color-ember-800)] dark:text-[var(--color-ember-400)] dark:hover:bg-[var(--color-ember-950)]/40',
  },
  dark: {
    primary: 'bg-[var(--color-verdant-600)] text-white hover:bg-[var(--color-verdant-500)]',
    secondary: 'border border-zinc-600 text-zinc-300 hover:bg-zinc-700',
    danger: 'bg-[var(--color-ember-600)] text-white hover:bg-[var(--color-ember-500)]',
  },
}

export function Button({ variant = 'secondary', tone, size = 'md', className, ...props }: Props) {
  const modalTone = useContext(ModalToneContext)
  const resolvedTone = tone ?? modalTone ?? 'light'
  return <button className={clsx('btn', SIZE[size], VARIANT[resolvedTone][variant], className)} {...props} />
}
