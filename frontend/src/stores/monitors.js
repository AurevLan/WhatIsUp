import { defineStore } from 'pinia'
import { ref } from 'vue'
import { monitorsApi } from '../api/monitors'

export const useMonitorStore = defineStore('monitors', () => {
  const monitors = ref([])
  const loading = ref(false)

  function enrich(m) {
    return {
      ...m,
      _lastStatus:          m.last_status ?? null,
      _uptime24h:           m.uptime_24h ?? null,
      _hasOpenIncident:     m.has_open_incident ?? false,
      _lastResponseTimeMs:  m.last_response_time_ms ?? null,
    }
  }

  async function fetchAll(params = {}) {
    loading.value = true
    try {
      const { data } = await monitorsApi.list(params)
      monitors.value = data.map(enrich)
    } finally {
      loading.value = false
    }
  }

  async function create(payload) {
    const { data } = await monitorsApi.create(payload)
    monitors.value.unshift(enrich(data))
    return data
  }

  async function update(id, payload) {
    const { data } = await monitorsApi.update(id, payload)
    const idx = monitors.value.findIndex(m => m.id === id)
    if (idx !== -1) monitors.value[idx] = enrich(data)
    return data
  }

  async function remove(id) {
    await monitorsApi.delete(id)
    monitors.value = monitors.value.filter(m => m.id !== id)
  }

  function applyCheckResult(event) {
    const monitor = monitors.value.find(m => m.id === event.monitor_id)
    if (monitor) {
      monitor._lastStatus          = event.status
      monitor._lastCheckedAt       = event.checked_at
      monitor._lastResponseTimeMs  = event.response_time_ms ?? monitor._lastResponseTimeMs
    }
  }

  return { monitors, loading, fetchAll, create, update, remove, applyCheckResult }
})
