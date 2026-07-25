import { render, screen } from '@testing-library/react'
import { describe, test, expect } from 'vitest'
import { Card } from '@/components/ui/Card'

describe('Card', () => {
  test('renders children inside the card shell', () => {
    render(<Card>Body content</Card>)
    expect(screen.getByText('Body content')).toBeInTheDocument()
  })

  test('applies padding variant', () => {
    render(<Card padding="lg">Padded</Card>)
    expect(screen.getByText('Padded')).toHaveClass('p-6')
  })

  test('merges a custom className', () => {
    render(<Card className="overflow-hidden">Custom</Card>)
    expect(screen.getByText('Custom')).toHaveClass('card', 'overflow-hidden')
  })
})
