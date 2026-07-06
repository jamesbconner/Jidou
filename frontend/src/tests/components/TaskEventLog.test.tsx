import { render, screen } from '@testing-library/react'
import { TaskEventLog } from '@/components/TaskEventLog'
import { describe, test, expect } from 'vitest'
import type { TaskEvent } from '@/types/api'

function makeEvents(count: number): TaskEvent[] {
  return Array.from({ length: count }, (_, i) => ({
    ts: new Date().toISOString(),
    level: 'info' as const,
    msg: `event ${i}`,
  }))
}

describe('TaskEventLog', () => {
  test('renders a message when there are no events', () => {
    render(<TaskEventLog events={[]} />)
    expect(screen.getByText('No events recorded yet.')).toBeInTheDocument()
  })

  test('renders each event message', () => {
    render(<TaskEventLog events={makeEvents(3)} />)
    expect(screen.getByText('event 0')).toBeInTheDocument()
    expect(screen.getByText('event 2')).toBeInTheDocument()
  })

  // Regression test: a prior implementation called scrollIntoView() on a
  // trailing sentinel div, which by default cascades scroll intent up
  // through every ancestor scrollable — including the page itself — forcing
  // the viewport to jump to the bottom every time a live task emitted a new
  // event. The fix sets scrollTop directly on the log container so no
  // ancestor (including window/document) is ever touched.
  test('autoscrolls the log container directly without using scrollIntoView', () => {
    const { container, rerender } = render(<TaskEventLog events={makeEvents(1)} live />)
    const logEl = container.querySelector('.overflow-y-auto') as HTMLDivElement
    expect(logEl).toBeTruthy()
    expect(logEl.scrollIntoView).toBeUndefined()

    Object.defineProperty(logEl, 'scrollHeight', { value: 500, configurable: true })
    logEl.scrollTop = 0

    rerender(<TaskEventLog events={makeEvents(2)} live />)

    expect(logEl.scrollTop).toBe(500)
  })

  test('does not autoscroll when not live', () => {
    const { container, rerender } = render(<TaskEventLog events={makeEvents(1)} live={false} />)
    const logEl = container.querySelector('.overflow-y-auto') as HTMLDivElement
    Object.defineProperty(logEl, 'scrollHeight', { value: 500, configurable: true })
    logEl.scrollTop = 0

    rerender(<TaskEventLog events={makeEvents(2)} live={false} />)

    expect(logEl.scrollTop).toBe(0)
  })
})
