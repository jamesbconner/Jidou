import { renderHook, act } from '@testing-library/react'
import { describe, test, expect, beforeEach } from 'vitest'
import { ThemeProvider, useColorScheme } from '@/stores/theme'

describe('ThemeProvider / useColorScheme', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  test('defaults to light with no dark class applied', () => {
    const { result } = renderHook(() => useColorScheme(), { wrapper: ThemeProvider })
    expect(result.current.colorScheme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  test('toggleColorScheme switches to dark, persists it, and applies the class', () => {
    const { result } = renderHook(() => useColorScheme(), { wrapper: ThemeProvider })
    act(() => {
      result.current.toggleColorScheme()
    })
    expect(result.current.colorScheme).toBe('dark')
    expect(JSON.parse(window.localStorage.getItem('jidou.colorScheme')!)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  test('toggling twice returns to light and removes the class', () => {
    const { result } = renderHook(() => useColorScheme(), { wrapper: ThemeProvider })
    act(() => {
      result.current.toggleColorScheme()
    })
    act(() => {
      result.current.toggleColorScheme()
    })
    expect(result.current.colorScheme).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })

  test('a fresh mount with dark already stored applies the class immediately', () => {
    window.localStorage.setItem('jidou.colorScheme', JSON.stringify('dark'))
    const { result } = renderHook(() => useColorScheme(), { wrapper: ThemeProvider })
    expect(result.current.colorScheme).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })

  test('setColorScheme sets an explicit value', () => {
    const { result } = renderHook(() => useColorScheme(), { wrapper: ThemeProvider })
    act(() => {
      result.current.setColorScheme('dark')
    })
    expect(result.current.colorScheme).toBe('dark')
  })
})
