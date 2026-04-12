import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useMonitorStore } from './monitors'
import { wsBaseUrl } from '../lib/serverConfig'

export const useWebSocketStore = defineStore('websocket', () => {
  const connected = ref(false)
  const showReconnecting = ref(false)
  const events = ref([])
  let ws = null
  let pingInterval = null
  let reconnectTimer = null
  let stopped = false
  let bannerTimer = null
  const BANNER_DELAY_MS = 2000  // avoid flashing on brief reconnects

  function _setBanner(show) {
    clearTimeout(bannerTimer)
    bannerTimer = null
    if (show) {
      bannerTimer = setTimeout(() => { showReconnecting.value = true; bannerTimer = null }, BANNER_DELAY_MS)
    } else {
      showReconnecting.value = false
    }
  }

  function connect() {
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) return
    stopped = false
    const token = localStorage.getItem('access_token')
    if (!token) return

    const url = `${wsBaseUrl()}/ws/dashboard`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      _setBanner(false)
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
        } else if (data.type === 'flapping_detected') {
          monitorStore.setFlapping(data.monitor_id)
        }
      } catch (err) {
        if (import.meta.env.DEV) console.error('[ws] message handler error:', err)
      }
    }

    ws.onclose = (event) => {
      connected.value = false
      clearInterval(pingInterval)
      pingInterval = null
      // 4001 = token rejected, or intentional disconnect — don't reconnect
      if (event.code === 4001 || stopped) return
      _setBanner(true)
      reconnectTimer = setTimeout(() => connect(), 5000)
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnect() {
    stopped = true
    clearTimeout(reconnectTimer)
    reconnectTimer = null
    clearTimeout(bannerTimer)
    showReconnecting.value = false
    clearInterval(pingInterval)
    pingInterval = null
    ws?.close()
    ws = null
    connected.value = false
  }

  return { connected, showReconnecting, events, connect, disconnect }
})
