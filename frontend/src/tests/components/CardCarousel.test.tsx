import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi, afterEach } from 'vitest'
import { CardCarousel } from '@/components/CardCarousel'

// jsdom reports scrollWidth/clientWidth as 0 for every element, so the
// carousel's overflow detection needs these mocked to exercise the
// scroll-button visibility logic.
function mockOverflow(clientWidth: number, scrollWidth: number) {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    value: clientWidth,
  })
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', {
    configurable: true,
    value: scrollWidth,
  })
}

describe('CardCarousel', () => {
  afterEach(() => {
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
    render(
      <CardCarousel>
        <div>Card A</div>
      </CardCarousel>,
    )

    const nextButton = screen.getByLabelText('Scroll right')
    expect(nextButton).toBeInTheDocument()
    expect(screen.queryByLabelText('Scroll left')).not.toBeInTheDocument()

    const scrollBySpy = vi.fn()
    HTMLElement.prototype.scrollBy = scrollBySpy

    fireEvent.click(nextButton)

    expect(scrollBySpy).toHaveBeenCalledWith(
      expect.objectContaining({ left: 180, behavior: 'smooth' }),
    )
  })
})
