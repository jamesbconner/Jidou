import { useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { Modal } from '@/components/ui/Modal'

describe('Modal', () => {
  test('renders children inside the panel', () => {
    render(
      <Modal onClose={vi.fn()}>
        <p>Panel content</p>
      </Modal>,
    )
    expect(screen.getByText('Panel content')).toBeInTheDocument()
  })

  test('applies the dark panel tone', () => {
    render(
      <Modal onClose={vi.fn()} tone="dark">
        <p>Dark content</p>
      </Modal>,
    )
    expect(screen.getByText('Dark content').parentElement).toHaveClass('panel-dark')
  })

  test('closes on Escape via useFocusTrap', () => {
    const onClose = vi.fn()
    render(
      <Modal onClose={onClose}>
        <p>Content</p>
      </Modal>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  test('Escape only closes the topmost of two stacked modals', () => {
    const outerClose = vi.fn()
    const innerClose = vi.fn()

    // Mirrors the real case (e.g. a confirmation dialog opened from within
    // another modal): the outer modal mounts first, and the inner one mounts
    // later in response to user interaction, not in the same initial render.
    function Stacked() {
      const [showInner, setShowInner] = useState(false)
      return (
        <Modal onClose={outerClose}>
          <p>Outer</p>
          <button onClick={() => setShowInner(true)}>Open inner</button>
          {showInner && (
            <Modal onClose={innerClose}>
              <p>Inner</p>
            </Modal>
          )}
        </Modal>
      )
    }

    render(<Stacked />)
    fireEvent.click(screen.getByText('Open inner'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(innerClose).toHaveBeenCalledTimes(1)
    expect(outerClose).not.toHaveBeenCalled()
  })
})
