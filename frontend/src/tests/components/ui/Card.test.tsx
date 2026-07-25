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

  test('renders as a section when requested', () => {
    render(<Card as="section">Landmark</Card>)
    expect(screen.getByText('Landmark').tagName).toBe('SECTION')
  })
})
