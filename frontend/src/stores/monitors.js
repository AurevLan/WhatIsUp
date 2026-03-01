import { defineStore } from 'pinia'
import { ref } from 'vue'
import { monitorsApi } from '../api/monitors'

export const useMonitorStore = defineStore('monitors', () => {
  const monitors = ref([])
  const loading = ref(false)

  async function fetchAll(params = {}) {
    loading.value = true
    try {
      const { data } = await monitorsApi.list(params)
      monitors.value = data.map(m => ({
        ...m,
        _lastStatus: m.last_status ?? null,
        _uptime24h: m.uptime_24h ?? null,
      }))
    } finally {
      loading.value = false
    }
  }

  async function create(payload) {
    const { data } = await monitorsApi.create(payload)
    monitors.value.unshift(data)
    return data
  }

  async function update(id, payload) {
    const { data } = await monitorsApi.update(id, payload)
    const idx = monitors.value.findIndex(m => m.id === id)
    if (idx !== -1) monitors.value[idx] = data
    return data
  }

  async function remove(id) {
    await monitorsApi.delete(id)
    monitors.value = monitors.value.filter(m => m.id !== id)
  }

  // Update monitor status from WebSocket event
  function applyCheckResult(event) {
    const monitor = monitors.value.find(m => m.id === event.monitor_id)
    if (monitor) {
      monitor._lastStatus = event.status
      monitor._lastCheckedAt = event.checked_at
    }
  }

  return { monitors, loading, fetchAll, create, update, remove, applyCheckResult }
})
