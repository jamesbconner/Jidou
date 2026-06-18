import { useWsConnectionState } from '@/stores/wsConnection'
import clsx from 'clsx'

export function ConnectionBadge() {
  const { state } = useWsConnectionState()

  const label =
    state === 'open' ? 'Live'
    : state === 'connecting' ? 'Connecting…'
    : state === 'closed' ? 'Reconnecting…'
    : null

  if (!label) return null

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
        state === 'open' && 'bg-green-100 text-green-700',
        state !== 'open' && 'bg-yellow-100 text-yellow-700',
      )}
    >
      <span
        className={clsx(
          'w-1.5 h-1.5 rounded-full',
          state === 'open' ? 'bg-green-500' : 'bg-yellow-500',
        )}
      />
      {label}
    </span>
  )
}
