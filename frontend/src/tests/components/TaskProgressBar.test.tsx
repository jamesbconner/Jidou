import { render, screen } from '@testing-library/react'
import { TaskProgressBar } from '@/components/TaskProgressBar'
import { describe, test, expect, vi } from 'vitest'
import type { TaskList } from '@/types/api'

const baseTask: TaskList = {
  id: 1,
  task_type: 'scan',
  status: 'running',
  progress_current: 5,
  progress_total: 20,
  progress_message: 'Scanning remote…',
  created_at: new Date().toISOString(),
  completed_at: null,
}

describe('TaskProgressBar', () => {
  test('renders task type and status', () => {
    render(<TaskProgressBar task={baseTask} />)
    expect(screen.getByText('scan')).toBeInTheDocument()
    expect(screen.getByText('running')).toBeInTheDocument()
  })

  test('shows progress message', () => {
    render(<TaskProgressBar task={baseTask} />)
    expect(screen.getByText('Scanning remote…')).toBeInTheDocument()
  })

  test('renders cancel button when onCancel provided and task is running', () => {
    const onCancel = vi.fn()
    render(<TaskProgressBar task={baseTask} onCancel={onCancel} />)
    expect(screen.getByText('Cancel')).toBeInTheDocument()
  })

  test('does not render cancel button for completed task', () => {
    render(<TaskProgressBar task={{ ...baseTask, status: 'completed' }} onCancel={vi.fn()} />)
    expect(screen.queryByText('Cancel')).not.toBeInTheDocument()
  })
})
