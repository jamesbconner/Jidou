import { useEffect, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { connectTaskProgress } from '@/api/websocket'
import { useWsConnectionState } from '@/stores/wsConnection'
import { taskKeys } from '@/hooks/useTasks'
import type { WsMessage, TaskRead, TaskList, TaskStatus } from '@/types/api'

// Track active WebSocket connections globally to avoid premature badge clearance
let activeConnections = 0
const connectionLock = new Object()

export function useTaskProgress(celeryTaskId: string | null) {
  const qc = useQueryClient()
  const { setState } = useWsConnectionState()
  const socketRef = useRef<ReturnType<typeof connectTaskProgress> | null>(null)

  const handleMessage = useCallback(
    (raw: unknown) => {
      if (!celeryTaskId) return
      const msg = raw as WsMessage

      // Update both the list query (TaskList[]) and detail query (TaskRead)
      qc.setQueriesData(
        { queryKey: taskKeys.list() },
        (oldList: unknown) => {
          if (!Array.isArray(oldList)) return oldList
          return oldList.map((item: TaskList) => {
            // Only update if this is the task we're listening to
            if ('celery_task_id' in item && (item as TaskRead).celery_task_id === celeryTaskId) {
              const task = item as TaskRead
              if (msg.type === 'progress') {
                return {
                  ...task,
                  progress_current: msg.data.current,
                  progress_total: msg.data.total,
                  progress_message: msg.data.message,
                  status: 'running' as TaskStatus,
                }
              }
              if (msg.type === 'complete') return { ...task, status: 'completed' as TaskStatus }
              if (msg.type === 'error') return { ...task, status: 'failed' as TaskStatus, progress_message: msg.data.error }
              if (msg.type === 'cancelled') return { ...task, status: 'cancelled' as TaskStatus }
            }
            return item
          })
        },
      )

      // Also update detail query if it exists
      qc.setQueriesData<TaskRead>(
        { queryKey: [taskKeys.all[0], 'detail'] },
        (old) => {
          if (!old || old.celery_task_id !== celeryTaskId) return old
          if (msg.type === 'progress') {
            return {
              ...old,
              progress_current: msg.data.current,
              progress_total: msg.data.total,
              progress_message: msg.data.message,
              status: 'running' as TaskStatus,
            }
          }
          if (msg.type === 'complete') return { ...old, status: 'completed' as TaskStatus }
          if (msg.type === 'error') return { ...old, status: 'failed' as TaskStatus, progress_message: msg.data.error }
          if (msg.type === 'cancelled') return { ...old, status: 'cancelled' as TaskStatus }
          return old
        },
      )
    },
    [celeryTaskId, qc],
  )

  useEffect(() => {
    if (!celeryTaskId) return

    socketRef.current = connectTaskProgress(celeryTaskId, handleMessage, setState)

    // Increment connection count when socket opens
    activeConnections++

    return () => {
      socketRef.current?.close()
      socketRef.current = null
      activeConnections--

      // Only clear badge if no connections remain
      if (activeConnections === 0) {
        setState('idle')
      }
    }
  }, [celeryTaskId, handleMessage, setState])
}
