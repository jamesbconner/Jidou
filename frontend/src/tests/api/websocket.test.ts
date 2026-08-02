import { describe, test, expect, vi, beforeEach, afterEach } from 'vitest'
import { connectTaskProgress } from '@/api/websocket'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closeCallCount = 0

  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }

  // A real close() would eventually fire onclose asynchronously; tests that
  // need to observe close-triggered side effects call it explicitly.
  close(): void {
    this.closeCallCount++
  }
}

const originalWebSocket = globalThis.WebSocket

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
})

afterEach(() => {
  vi.useRealTimers()
  globalThis.WebSocket = originalWebSocket
})

describe('connectTaskProgress — reconnect timer lifecycle', () => {
  test('an ordinary disconnect reconnects after the retry delay', () => {
    connectTaskProgress('task-1', vi.fn(), vi.fn())

    expect(FakeWebSocket.instances.length).toBe(1)
    FakeWebSocket.instances[0].onclose?.()

    // Reconnect is scheduled, not immediate.
    expect(FakeWebSocket.instances.length).toBe(1)
    vi.advanceTimersByTime(1000)
    expect(FakeWebSocket.instances.length).toBe(2)
  })

  test('close() cancels a pending reconnect timer instead of letting it fire', () => {
    // Regression test: the reconnect timer scheduled by onclose was never
    // captured or cancelled, so a disconnect immediately followed by close()
    // (e.g. the user navigating away right after a network blip) let the
    // already-scheduled timer fire anyway, opening a zombie connection with
    // stale callbacks that nothing tracks or closes.
    const managed = connectTaskProgress('task-1', vi.fn(), vi.fn())

    FakeWebSocket.instances[0].onclose?.() // disconnect schedules a reconnect
    managed.close() // caller navigates away before the timer fires

    vi.advanceTimersByTime(30_000) // well past the retry delay
    expect(FakeWebSocket.instances.length).toBe(1)
  })

  test('close() closes the current socket', () => {
    const managed = connectTaskProgress('task-1', vi.fn(), vi.fn())

    managed.close()

    expect(FakeWebSocket.instances[0].closeCallCount).toBe(1)
  })

  test('onStateChange is not called again by a reconnect timer that fired after close()', () => {
    const onStateChange = vi.fn()
    const managed = connectTaskProgress('task-1', vi.fn(), onStateChange)

    FakeWebSocket.instances[0].onclose?.()
    managed.close()
    onStateChange.mockClear()

    vi.advanceTimersByTime(30_000)

    // A zombie reconnect would call onStateChange('connecting') here.
    expect(onStateChange).not.toHaveBeenCalled()
  })
})
