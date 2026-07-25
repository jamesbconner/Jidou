import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { Badge } from '@/components/ui/Badge'

describe('Badge', () => {
  test('renders as a span with the given color classes', () => {
    render(<Badge color="bg-green-100 text-green-700">active</Badge>)
    const el = screen.getByText('active')
    expect(el.tagName).toBe('SPAN')
    expect(el).toHaveClass('bg-green-100', 'text-green-700')
  })

  test('renders as a clickable button when onClick is given', () => {
    const onClick = vi.fn()
    render(
      <Badge color="bg-blue-100 text-blue-700" onClick={onClick} title="Click to change status">
        Watching
      </Badge>,
    )
    const el = screen.getByText('Watching')
    expect(el.tagName).toBe('BUTTON')
    fireEvent.click(el)
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
