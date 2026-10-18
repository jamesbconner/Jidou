import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, act } from '@testing-library/react'
import { describe, test, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { useTaskProgress } from '@/hooks/useTaskProgress'
import { taskKeys } from '@/hooks/useTasks'
import type { TaskList } from '@/types/api'

let deliver: (msg: unknown) => void = () => {}

vi.mock('@/api/websocket', () => ({
  connectTaskProgress: (_id: string, onMessage: (msg: unknown) => void) => {
    deliver = onMessage
    return { close: () => {} }
  },
}))

function makeTask(id: number): TaskList {
  return {
    id,
    task_type: 'refresh_show_metadata',
    status: 'pending',
    progress_current: 0,
    progress_total: 0,
    progress_message: null,
    result_summary: null,
    dry_run: false,
    created_at: '2026-10-17T00:00:00Z',
    completed_at: null,
  }
}

describe('useTaskProgress', () => {
  let qc: QueryClient
  const listKey = taskKeys.list({ limit: 20, offset: 0 })

  beforeEach(() => {
    qc = new QueryClient()
    qc.setQueryData<TaskList[]>(listKey, [makeTask(1), makeTask(2)])
  })

  function mount(celeryTaskId: string, taskId: number) {
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children)
    renderHook(() => useTaskProgress(celeryTaskId, taskId), { wrapper })
  }

  test('a progress message updates the matching row of the cached task list', () => {
    mount('celery-2', 2)

    act(() =>
      deliver({
        celery_task_id: 'celery-2',
        type: 'progress',
        data: { current: 3, total: 10, message: 'Refreshing Show' },
      }),
    )

    const [first, second] = qc.getQueryData<TaskList[]>(listKey)!
    expect(second).toMatchObject({
      status: 'running',
      progress_current: 3,
      progress_total: 10,
      progress_message: 'Refreshing Show',
    })
    expect(first.progress_current).toBe(0)
  })

  test('a complete message marks only the matching row completed', () => {
    mount('celery-1', 1)

    act(() => deliver({ celery_task_id: 'celery-1', type: 'complete', data: {} }))

    const [first, second] = qc.getQueryData<TaskList[]>(listKey)!
    expect(first.status).toBe('completed')
    expect(second.status).toBe('pending')
  })
})
