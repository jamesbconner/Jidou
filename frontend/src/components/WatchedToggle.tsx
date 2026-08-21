interface Props {
  watched: boolean
  onToggle: () => void
  disabled?: boolean
}

export function WatchedToggle({ watched, onToggle, disabled = false }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={watched}
      aria-label={watched ? 'Mark episode unwatched' : 'Mark episode watched'}
      title={watched ? 'Mark unwatched' : 'Mark watched'}
      onClick={onToggle}
      disabled={disabled}
      className={`relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 disabled:cursor-wait ${
        watched ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-700'
      }`}
    >
      <span
        className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
          watched ? 'translate-x-3.5' : 'translate-x-0.5'
        }`}
      />
    </button>
  )
}
