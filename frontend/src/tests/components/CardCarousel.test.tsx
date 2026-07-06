import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi, afterEach } from 'vitest'
import { CardCarousel } from '@/components/CardCarousel'

// jsdom reports scrollWidth/clientWidth as 0 (and has no scrollBy at all) for
// every element, so the carousel's overflow detection and scroll behaviour
// need these mocked. Tests run with `isolate: false` (see vitest.config.ts),
// meaning all test files share one process — mutating HTMLElement.prototype
// without restoring it would leak into every other test file, so the
// original descriptors are always saved and restored.
const ORIGINAL_DESCRIPTORS = {
  clientWidth: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth'),
  scrollWidth: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollWidth'),
  scrollBy: Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollBy'),
}

function mockOverflow(clientWidth: number, scrollWidth: number) {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: clientWidth })
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, value: scrollWidth })
}

function restorePrototype() {
  for (const [prop, descriptor] of Object.entries(ORIGINAL_DESCRIPTORS)) {
    if (descriptor) {
      Object.defineProperty(HTMLElement.prototype, prop, descriptor)
    } else {
      delete (HTMLElement.prototype as unknown as Record<string, unknown>)[prop]
    }
  }
}

describe('CardCarousel', () => {
  afterEach(() => {
    restorePrototype()
    vi.restoreAllMocks()
  })

  test('renders its children', () => {
    render(
      <CardCarousel>
        <div>Card A</div>
        <div>Card B</div>
      </CardCarousel>,
    )
    expect(screen.getByText('Card A')).toBeInTheDocument()
    expect(screen.getByText('Card B')).toBeInTheDocument()
  })

  test('hides both scroll buttons when content does not overflow', () => {
    mockOverflow(500, 500)
    render(
      <CardCarousel>
        <div>Card A</div>
      </CardCarousel>,
    )
    expect(screen.queryByLabelText('Scroll left')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Scroll right')).not.toBeInTheDocument()
  })

  test('shows the next button and scrolls forward when content overflows', () => {
    mockOverflow(200, 1000)
    const scrollBySpy = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollBy', {
      configurable: true,
      value: scrollBySpy,
    })

    render(
      <CardCarousel>
        <div>Card A</div>
      </CardCarousel>,
    )

    const nextButton = screen.getByLabelText('Scroll right')
    expect(nextButton).toBeInTheDocument()
    expect(screen.queryByLabelText('Scroll left')).not.toBeInTheDocument()

    fireEvent.click(nextButton)

    expect(scrollBySpy).toHaveBeenCalledWith(
      expect.objectContaining({ left: 180, behavior: 'smooth' }),
    )
  })
})
