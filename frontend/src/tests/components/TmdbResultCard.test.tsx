import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, test, expect, vi } from 'vitest'
import { TmdbResultCard } from '@/components/TmdbResultCard'

const result = { poster_path: '/poster.jpg', name: 'Test Show', title: null }

function renderCard(props: Partial<Parameters<typeof TmdbResultCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <TmdbResultCard result={result} onAdd={vi.fn()} addPending={false} {...props} />
    </MemoryRouter>,
  )
}

describe('TmdbResultCard', () => {
  test('renders poster and title', () => {
    renderCard()
    expect(screen.getByRole('img', { name: 'Test Show' })).toHaveAttribute(
      'src',
      '/api/images/w185/poster.jpg',
    )
    expect(screen.getByText('Test Show')).toBeInTheDocument()
  })

  test('clicking the card calls onCardClick when provided', () => {
    const onCardClick = vi.fn()
    renderCard({ onCardClick })
    fireEvent.click(screen.getByText('Test Show'))
    expect(onCardClick).toHaveBeenCalledTimes(1)
  })

  test('clicking Add does not also trigger onCardClick', () => {
    const onCardClick = vi.fn()
    const onAdd = vi.fn()
    renderCard({ onCardClick, onAdd })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    expect(onAdd).toHaveBeenCalledTimes(1)
    expect(onCardClick).not.toHaveBeenCalled()
  })

  test('clicking "View in Library" does not also trigger onCardClick', () => {
    const onCardClick = vi.fn()
    const onNavigate = vi.fn()
    renderCard({ onCardClick, onNavigate, inLibraryShowId: 42 })
    fireEvent.click(screen.getByText('View in Library'))
    expect(onNavigate).toHaveBeenCalledTimes(1)
    expect(onCardClick).not.toHaveBeenCalled()
  })

  test('no cursor-pointer styling when onCardClick is omitted', () => {
    renderCard()
    expect(screen.getByText('Test Show').closest('.card')).not.toHaveClass('cursor-pointer')
  })
})
