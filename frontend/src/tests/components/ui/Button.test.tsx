import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'

describe('Button', () => {
  test('renders children and handles click', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Save</Button>)
    fireEvent.click(screen.getByText('Save'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  test('applies primary variant classes', () => {
    render(<Button variant="primary">Confirm</Button>)
    expect(screen.getByText('Confirm')).toHaveClass('bg-[var(--color-verdant-600)]')
  })

  test('applies dark tone danger classes', () => {
    render(
      <Button variant="danger" tone="dark">
        Delete
      </Button>,
    )
    expect(screen.getByText('Delete')).toHaveClass('bg-[var(--color-ember-600)]')
  })

  test('respects disabled prop', () => {
    render(<Button disabled>Busy</Button>)
    expect(screen.getByText('Busy')).toBeDisabled()
  })

  test('inherits tone from an enclosing Modal when not set explicitly', () => {
    render(
      <Modal onClose={vi.fn()} tone="dark">
        <Button variant="secondary">Cancel</Button>
      </Modal>,
    )
    expect(screen.getByText('Cancel')).toHaveClass('border-zinc-600')
  })

  test('an explicit tone prop overrides the enclosing Modal tone', () => {
    render(
      <Modal onClose={vi.fn()} tone="dark">
        <Button variant="secondary" tone="light">
          Cancel
        </Button>
      </Modal>,
    )
    expect(screen.getByText('Cancel')).toHaveClass('border-gray-300')
  })
})
