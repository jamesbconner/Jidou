export type WsCallback = (data: unknown) => void

export interface ManagedWebSocket {
  close: () => void
}

/** Open a WebSocket to /ws/task-progress/{celeryTaskId} with auto-reconnect. */
export function connectTaskProgress(
  celeryTaskId: string,
  onMessage: WsCallback,
  onStateChange: (state: 'connecting' | 'open' | 'closed') => void,
): ManagedWebSocket {
  let ws: WebSocket | null = null
  let stopped = false
  let retryDelay = 1000
  const MAX_DELAY = 30_000

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    onStateChange('connecting')
    ws = new WebSocket(`${proto}://${location.host}/ws/task-progress/${celeryTaskId}`)

    ws.onopen = () => {
      retryDelay = 1000
      onStateChange('open')
    }

    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data as string))
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      onStateChange('closed')
      if (!stopped) {
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, MAX_DELAY)
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  connect()

  return {
    close() {
      stopped = true
      ws?.close()
    },
  }
}
