import { useEffect, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { connectTaskProgress } from '@/api/websocket'
import { useWsConnectionState } from '@/stores/wsConnection'
import { taskKeys } from '@/hooks/useTasks'
import type { WsMessage, TaskRead, TaskStatus } from '@/types/api'

export function useTaskProgress(celeryTaskId: string | null) {
  const qc = useQueryClient()
  const { setState } = useWsConnectionState()
  const socketRef = useRef<ReturnType<typeof connectTaskProgress> | null>(null)

  const handleMessage = useCallback(
    (raw: unknown) => {
      if (!celeryTaskId) return
      const msg = raw as WsMessage

      qc.setQueriesData<TaskRead>(
        { queryKey: taskKeys.all },
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
          if (msg.type === 'complete') {
            return { ...old, status: 'completed' as TaskStatus }
          }
          if (msg.type === 'error') {
            return { ...old, status: 'failed' as TaskStatus, progress_message: msg.data.error }
          }
          if (msg.type === 'cancelled') {
            return { ...old, status: 'cancelled' as TaskStatus }
          }
          return old
        },
      )
    },
    [celeryTaskId, qc],
  )

  useEffect(() => {
    if (!celeryTaskId) return
    socketRef.current = connectTaskProgress(celeryTaskId, handleMessage, setState)
    return () => {
      socketRef.current?.close()
      socketRef.current = null
      setState('idle')
    }
  }, [celeryTaskId, handleMessage, setState])
}
