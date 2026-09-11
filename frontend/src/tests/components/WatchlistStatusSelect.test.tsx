import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { WatchlistStatusSelect } from '@/components/WatchlistStatusSelect'

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, children)
}

// vi.spyOn(globalThis, 'fetch') triggers a worker crash on Node >=22.1.x
// (https://github.com/nodejs/node/issues/54735); plain assignment avoids it.
const originalFetch = globalThis.fetch

beforeEach(() => {
  globalThis.fetch = vi.fn()
})

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('WatchlistStatusSelect', () => {
  test('the editing <select> pairs an explicit background with an explicit text colour in both themes', () => {
    // Regression: a <select>/<option> with only a background (or only a text
    // colour) in one theme relies on an inherited colour for the other half,
    // which the browser's native dropdown popup does not reliably match —
    // producing invisible (bg-on-bg) text in light mode, dark mode, or both.
    render(createElement(WatchlistStatusSelect, { id: 1, current: 'planned' }), {
      wrapper: makeWrapper(),
    })

    fireEvent.click(screen.getByRole('button', { name: 'Planned' }))

    const select = screen.getByRole('combobox')
    expect(select.className).toMatch(/\bbg-white\b/)
    expect(select.className).toMatch(/\btext-gray-900\b/)
    expect(select.className).toMatch(/\bdark:bg-gray-800\b/)
    expect(select.className).toMatch(/\bdark:text-gray-100\b/)

    const options = select.querySelectorAll('option')
    expect(options.length).toBeGreaterThan(0)
    options.forEach((opt) => {
      expect(opt.className).toMatch(/\bbg-white\b/)
      expect(opt.className).toMatch(/\btext-gray-900\b/)
      expect(opt.className).toMatch(/\bdark:bg-gray-800\b/)
      expect(opt.className).toMatch(/\bdark:text-gray-100\b/)
    })
  })
})
