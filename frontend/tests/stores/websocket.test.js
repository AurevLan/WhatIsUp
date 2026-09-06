import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('../../src/lib/serverConfig', () => ({
  wsBaseUrl: () => 'ws://api.example',
  apiBaseUrl: () => 'http://api.example/api/v1',
  isNative: () => false,
}))

const monitorStore = {
  applyCheckResult: vi.fn(),
}
vi.mock('../../src/stores/monitors', () => ({
  useMonitorStore: () => monitorStore,
}))

import { useWebSocketStore } from '../../src/stores/websocket'

// Spy-friendly mock WebSocket. Each constructor call records the instance
// on `MockWebSocket.last` so tests can drive lifecycle events from outside.
class MockWebSocket {
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3
  static last = null
  static instances = []

  constructor(url) {
    this.url = url
    this.readyState = MockWebSocket.CONNECTING
    this.send = vi.fn()
    this.close = vi.fn(() => {
      this.readyState = MockWebSocket.CLOSED
      this.onclose?.({ code: 1000 })
    })
    this.onopen = null
    this.onmessage = null
    this.onclose = null
    this.onerror = null
    MockWebSocket.last = this
    MockWebSocket.instances.push(this)
  }

  triggerOpen() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  triggerClose(code) {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.({ code })
  }
}

let originalWS

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  monitorStore.applyCheckResult.mockReset()
  MockWebSocket.last = null
  MockWebSocket.instances.length = 0
  originalWS = globalThis.WebSocket
  globalThis.WebSocket = MockWebSocket
  vi.useFakeTimers()
})

afterEach(() => {
  globalThis.WebSocket = originalWS
  vi.useRealTimers()
})

describe('websocket store', () => {
  it('does not connect when no access token is stored', () => {
    const ws = useWebSocketStore()
    ws.connect()
    expect(MockWebSocket.last).toBe(null)
  })

  it('opens the connection at /ws/dashboard with no token in URL (security)', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    expect(MockWebSocket.last.url).toBe('ws://api.example/ws/dashboard')
    // the token MUST NOT appear in the URL (ANSSI / SECURITY.md §6)
    expect(MockWebSocket.last.url).not.toContain('tk')
  })

  it('sends the auth frame as the first message after onopen', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    expect(MockWebSocket.last.send).toHaveBeenCalledWith(JSON.stringify({ type: 'auth', token: 'tk' }))
    expect(ws.connected).toBe(true)
  })

  it('schedules a 30s ping interval after auth and stops it on close', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()

    const sendBefore = MockWebSocket.last.send.mock.calls.length
    vi.advanceTimersByTime(30000)
    expect(MockWebSocket.last.send.mock.calls.length).toBe(sendBefore + 1)
    expect(MockWebSocket.last.send).toHaveBeenLastCalledWith('ping')

    // close → ping interval cleared. Use disconnect() so no reconnect timer
    // creates a second ws instance under our feet.
    const captured = MockWebSocket.last
    ws.disconnect()
    const sendAfterClose = captured.send.mock.calls.length
    vi.advanceTimersByTime(30000)
    expect(captured.send.mock.calls.length).toBe(sendAfterClose)
  })

  it('routes check_result messages to the monitor store', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()

    MockWebSocket.last.onmessage({ data: JSON.stringify({ type: 'check_result', monitor_id: 'm1', status: 'up' }) })
    expect(monitorStore.applyCheckResult).toHaveBeenCalledWith({ type: 'check_result', monitor_id: 'm1', status: 'up' })

    expect(ws.events.length).toBe(1)
  })

  it('caps the events buffer at 100 entries', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()

    for (let i = 0; i < 110; i++) {
      MockWebSocket.last.onmessage({ data: JSON.stringify({ type: 'noise', i }) })
    }
    expect(ws.events.length).toBe(100)
  })

  it('does not reconnect when token rejected (code 4001)', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    MockWebSocket.last.triggerClose(4001)

    vi.advanceTimersByTime(10000)
    // only the original instance should exist
    expect(MockWebSocket.instances.length).toBe(1)
  })

  it('reconnects after 5s when the close was unexpected', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    MockWebSocket.last.triggerClose(1006)

    vi.advanceTimersByTime(5000)
    expect(MockWebSocket.instances.length).toBe(2)
  })

  it('disconnect() prevents subsequent reconnects (stopped flag honored)', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    ws.disconnect()

    vi.advanceTimersByTime(10000)
    expect(MockWebSocket.instances.length).toBe(1)
    expect(ws.connected).toBe(false)
  })

  it('reconnect banner is delayed by 2s to avoid flashing', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    MockWebSocket.last.triggerClose(1006)

    expect(ws.showReconnecting).toBe(false)
    vi.advanceTimersByTime(1900)
    expect(ws.showReconnecting).toBe(false)
    vi.advanceTimersByTime(200)
    expect(ws.showReconnecting).toBe(true)
  })

  it('connect is idempotent when already open', () => {
    localStorage.setItem('access_token', 'tk')
    const ws = useWebSocketStore()
    ws.connect()
    MockWebSocket.last.triggerOpen()
    ws.connect()
    expect(MockWebSocket.instances.length).toBe(1)
  })
})
