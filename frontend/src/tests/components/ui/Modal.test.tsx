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
})
