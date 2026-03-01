import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useMonitorStore } from './monitors'

export const useWebSocketStore = defineStore('websocket', () => {
  const connected = ref(false)
  const events = ref([])
  let ws = null

  function connect() {
    const token = localStorage.getItem('access_token')
    if (!token) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/dashboard?token=${encodeURIComponent(token)}`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      // Send ping every 30s to keep alive
      setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 30000)
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
      } catch {}
    }

    ws.onclose = (event) => {
      connected.value = false
      // 4001 = token rejected — don't reconnect, let the HTTP interceptor handle token refresh
      if (event.code === 4001) return
      // Reconnect after 5s (fresh token will be picked up from localStorage)
      setTimeout(() => connect(), 5000)
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function disconnect() {
    ws?.close()
    ws = null
    connected.value = false
  }

  return { connected, events, connect, disconnect }
})
