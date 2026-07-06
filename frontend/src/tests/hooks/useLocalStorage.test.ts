import { renderHook, act } from '@testing-library/react'
import { describe, test, expect, beforeEach } from 'vitest'
import { useLocalStorageState } from '@/hooks/useLocalStorage'

describe('useLocalStorageState', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  test('returns the default value when the key is absent', () => {
    const { result } = renderHook(() => useLocalStorageState('test.key', { count: 0 }))
    expect(result.current[0]).toEqual({ count: 0 })
  })

  test('restores a previously stored value', () => {
    window.localStorage.setItem('test.key', JSON.stringify({ count: 5 }))
    const { result } = renderHook(() => useLocalStorageState('test.key', { count: 0 }))
    expect(result.current[0]).toEqual({ count: 5 })
  })

  test('writes through on set and updates the returned value', () => {
    const { result } = renderHook(() => useLocalStorageState('test.key', { count: 0 }))
    act(() => {
      result.current[1]({ count: 9 })
    })
    expect(result.current[0]).toEqual({ count: 9 })
    expect(JSON.parse(window.localStorage.getItem('test.key')!)).toEqual({ count: 9 })
  })

  test('falls back to the default when stored JSON is malformed', () => {
    window.localStorage.setItem('test.key', 'not valid json{')
    const { result } = renderHook(() => useLocalStorageState('test.key', { count: 0 }))
    expect(result.current[0]).toEqual({ count: 0 })
  })
})
