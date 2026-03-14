import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useMonitorStore } from './monitors'

export const useWebSocketStore = defineStore('websocket', () => {
  const connected = ref(false)
  const events = ref([])
  let ws = null
  let pingInterval = null  // track interval to prevent leak
  let stopped = false     // set by disconnect() to prevent auto-reconnect

  function connect() {
    stopped = false
    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/dashboard`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      // H-06: send auth frame (token not exposed in URL/logs)
      ws.send(JSON.stringify({ type: 'auth', token }))
      // Keep-alive ping every 30s — store interval to clear on disconnect
      pingInterval = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 30000)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        events.value.unshift(data)
        if (events.value.length > 100) events.value.pop()

        const monitorStore = useMonitorStore()
        if (data.type === 'check_result') {
          monitorStore.applyCheckResult(data)
        }
      } catch (err) {
        console.error('[ws] message handler error:', err)
      }
    }

    ws.onclose = (event) => {
      connected.value = false
      clearInterval(pingInterval)
      pingInterval = null
      // 4001 = token rejected, or intentional disconnect — don't reconnect
      if (event.code === 4001 || stopped) return
      // Reconnect after 5s (fresh token will be picked up from localStorage)
      setTimeout(() => connect(), 5000)
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnect() {
    stopped = true
    clearInterval(pingInterval)
    pingInterval = null
    ws?.close()
    ws = null
    connected.value = false
  }

  return { connected, events, connect, disconnect }
})
