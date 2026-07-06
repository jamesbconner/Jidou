import { useState } from 'react'

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Persists state to localStorage under `key`, restoring it on mount.
 * Falls back to `defaultValue` when the key is absent or its stored
 * value is not valid JSON. When both the default and the stored value are
 * plain objects, they are shallow-merged so a partial or stale stored
 * value (e.g. from an older app version that had fewer fields) can't leave
 * a required key undefined.
 */
export function useLocalStorageState<T>(key: string, defaultValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === 'undefined') return defaultValue
    try {
      const stored = window.localStorage.getItem(key)
      if (stored === null) return defaultValue
      const parsed = JSON.parse(stored) as T
      if (isPlainObject(defaultValue) && isPlainObject(parsed)) {
        return { ...defaultValue, ...parsed } as T
      }
      return parsed
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
