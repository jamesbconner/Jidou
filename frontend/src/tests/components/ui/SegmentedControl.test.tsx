import { render, screen, fireEvent } from '@testing-library/react'
import { describe, test, expect, vi } from 'vitest'
import { SegmentedControl } from '@/components/ui/SegmentedControl'

const OPTIONS = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
  { value: 'c', label: 'C', disabled: true, disabledReason: 'Not available' },
]

describe('SegmentedControl', () => {
  test('renders every option', () => {
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="a" onChange={vi.fn()} />)
    expect(screen.getByText('A')).toBeInTheDocument()
    expect(screen.getByText('B')).toBeInTheDocument()
    expect(screen.getByText('C')).toBeInTheDocument()
  })

  test('marks the active option as checked', () => {
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="b" onChange={vi.fn()} />)
    expect(screen.getByText('A')).toHaveAttribute('aria-checked', 'false')
    expect(screen.getByText('B')).toHaveAttribute('aria-checked', 'true')
  })

  test('clicking an enabled option calls onChange with its value', () => {
    const onChange = vi.fn()
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="a" onChange={onChange} />)
    fireEvent.click(screen.getByText('B'))
    expect(onChange).toHaveBeenCalledWith('b')
  })

  test('clicking a disabled option does not call onChange', () => {
    const onChange = vi.fn()
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="a" onChange={onChange} />)
    fireEvent.click(screen.getByText('C'))
    expect(onChange).not.toHaveBeenCalled()
  })

  test('disabled option is disabled and exposes its reason as a title', () => {
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="a" onChange={vi.fn()} />)
    expect(screen.getByText('C')).toBeDisabled()
    expect(screen.getByText('C')).toHaveAttribute('title', 'Not available')
  })

  test('enabled options have no title attribute', () => {
    render(<SegmentedControl aria-label="Test" options={OPTIONS} value="a" onChange={vi.fn()} />)
    expect(screen.getByText('A')).not.toHaveAttribute('title')
  })
})
