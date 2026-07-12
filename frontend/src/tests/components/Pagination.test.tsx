import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Pagination } from '@/components/Pagination'
import { describe, test, expect, vi } from 'vitest'

describe('Pagination', () => {
  test('renders nothing when there is only one page', () => {
    const onPageChange = vi.fn()
    const { container } = render(<Pagination page={0} totalPages={1} onPageChange={onPageChange} />)
    expect(container).toBeEmptyDOMElement()
  })

  test('First/Prev are disabled on the first page', () => {
    render(<Pagination page={0} totalPages={10} onPageChange={vi.fn()} />)
    expect(screen.getByTitle('First page')).toBeDisabled()
    expect(screen.getByTitle('Previous page')).toBeDisabled()
    expect(screen.getByTitle('Next page')).toBeEnabled()
    expect(screen.getByTitle('Last page')).toBeEnabled()
  })

  test('Next/Last are disabled on the last page', () => {
    render(<Pagination page={9} totalPages={10} onPageChange={vi.fn()} />)
    expect(screen.getByTitle('Next page')).toBeDisabled()
    expect(screen.getByTitle('Last page')).toBeDisabled()
    expect(screen.getByTitle('First page')).toBeEnabled()
    expect(screen.getByTitle('Previous page')).toBeEnabled()
  })

  test('clicking Next/Prev/First/Last calls onPageChange with the right target', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={5} totalPages={10} onPageChange={onPageChange} />)

    await user.click(screen.getByTitle('Next page'))
    expect(onPageChange).toHaveBeenLastCalledWith(6)

    await user.click(screen.getByTitle('Previous page'))
    expect(onPageChange).toHaveBeenLastCalledWith(4)

    await user.click(screen.getByTitle('First page'))
    expect(onPageChange).toHaveBeenLastCalledWith(0)

    await user.click(screen.getByTitle('Last page'))
    expect(onPageChange).toHaveBeenLastCalledWith(9)
  })

  test('typing a page number and blurring jumps to that page (1-indexed input, 0-indexed callback)', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={0} totalPages={164} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page')
    await user.clear(input)
    await user.type(input, '140')
    await user.tab()

    expect(onPageChange).toHaveBeenCalledWith(139)
  })

  test('jump input clamps values above totalPages', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={0} totalPages={10} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page')
    await user.clear(input)
    await user.type(input, '9999')
    await user.tab()

    expect(onPageChange).toHaveBeenCalledWith(9)
  })

  test('jump input clamps values below 1', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={5} totalPages={10} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page')
    await user.clear(input)
    await user.type(input, '0')
    await user.tab()

    expect(onPageChange).toHaveBeenCalledWith(0)
  })

  test('an invalid (empty) jump input reverts to the current page without calling onPageChange', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={3} totalPages={10} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page') as HTMLInputElement
    await user.clear(input)
    await user.tab()

    expect(onPageChange).not.toHaveBeenCalled()
    expect(input.value).toBe('4')
  })

  test('jumping to the already-current page does not call onPageChange', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={4} totalPages={10} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page')
    await user.clear(input)
    await user.type(input, '5')
    await user.tab()

    expect(onPageChange).not.toHaveBeenCalled()
  })

  test('pressing Enter in the jump input commits the value', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    render(<Pagination page={0} totalPages={10} onPageChange={onPageChange} />)

    const input = screen.getByLabelText('Go to page')
    await user.clear(input)
    await user.type(input, '7{Enter}')

    expect(onPageChange).toHaveBeenCalledWith(6)
  })

  test('the jump input resyncs when the page prop changes externally', () => {
    const { rerender } = render(<Pagination page={0} totalPages={10} onPageChange={vi.fn()} />)
    const input = screen.getByLabelText('Go to page') as HTMLInputElement
    expect(input.value).toBe('1')

    rerender(<Pagination page={7} totalPages={10} onPageChange={vi.fn()} />)
    expect(input.value).toBe('8')
  })
})
