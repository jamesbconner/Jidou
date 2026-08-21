import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, beforeEach } from 'vitest'
import { ThemeToggle } from '@/components/ui/ThemeToggle'
import { ThemeProvider } from '@/stores/theme'

describe('ThemeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  test('renders with an accessible name reflecting light mode by default', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    )
    expect(screen.getByRole('button', { name: /switch to dark mode/i })).toHaveAttribute('aria-pressed', 'false')
  })

  test('clicking flips the accessible name, aria-pressed, and the dark class', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: /switch to dark mode/i }))
    expect(screen.getByRole('button', { name: /switch to light mode/i })).toHaveAttribute('aria-pressed', 'true')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
