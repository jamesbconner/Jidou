import clsx from 'clsx'

export interface SegmentedOption<T extends string | number> {
  value: T
  label: string
  disabled?: boolean
  disabledReason?: string
}

interface Props<T extends string | number> {
  options: SegmentedOption<T>[]
  value: T
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  className?: string
  'aria-label': string
}

const SIZE = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
}

// Rendered as a row of individually-bordered buttons rather than a joined
// pill, matching how Prev/Today/Next already appear as separate bordered
// buttons in Calendar.tsx. Light-only for now — there's no dark-mode
// consumer yet (Calendar never renders inside a dark Modal); extend the way
// Button.tsx does (ModalToneContext) if that changes.
export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  size = 'sm',
  className,
  'aria-label': ariaLabel,
}: Props<T>) {
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={clsx('flex gap-1', className)}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={option.disabled}
            title={option.disabled ? option.disabledReason : undefined}
            onClick={() => onChange(option.value)}
            className={clsx(
              'rounded border font-medium focus:outline-none focus:ring-2 focus:ring-blue-500',
              SIZE[size],
              active
                ? 'bg-[var(--color-ocean-600)] text-white border-[var(--color-ocean-600)]'
                : 'border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800',
              option.disabled && 'opacity-50 cursor-not-allowed hover:bg-transparent',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
