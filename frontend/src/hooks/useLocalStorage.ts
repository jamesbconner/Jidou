import { useState } from 'react'

/**
 * Persists state to localStorage under `key`, restoring it on mount.
 * Falls back to `defaultValue` when the key is absent or its stored
 * value is not valid JSON.
 */
export function useLocalStorageState<T>(key: string, defaultValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === 'undefined') return defaultValue
    try {
      const stored = window.localStorage.getItem(key)
      return stored === null ? defaultValue : (JSON.parse(stored) as T)
    } catch {
      return defaultValue
    }
  })

  function set(next: T) {
    setValue(next)
    try {
      window.localStorage.setItem(key, JSON.stringify(next))
    } catch {
      // Storage unavailable (private browsing, quota exceeded, etc.) —
      // state still updates in memory for the current session.
    }
  }

  return [value, set] as const
}
