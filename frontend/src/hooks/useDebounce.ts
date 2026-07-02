import { useState, useEffect } from 'react'

/**
 * Returns a debounced copy of `value` that only updates after `delayMs`
 * milliseconds have elapsed since the last change.
 */
export function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
