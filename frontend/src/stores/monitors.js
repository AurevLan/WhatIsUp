import { defineStore } from 'pinia'
import { ref } from 'vue'
import { monitorsApi } from '../api/monitors'

// Auto-clear flapping state after 10 minutes (matches default flap_window_minutes)
const FLAP_TTL_MS = 10 * 60 * 1000
const flapTimers = {}

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
      _p95ResponseTimeMs:   m.p95_response_time_ms ?? null,
      _sparkline:           m.sparkline ?? [],
      _isFlapping:          false,
      _healthScore:         _computeHealth(m),
    }
  }

  function _computeHealth(m) {
    const uptime = m.uptime_24h ?? null
    const hasIncident = m.has_open_incident ?? false
    const rt = m.last_response_time_ms ?? null
    const p95 = m.p95_response_time_ms ?? null

    if (uptime == null) return null

    // Score 0-100: uptime 60%, response time 25% (relative to p95), incident penalty 15%
    let score = uptime * 0.6
    if (rt != null && p95 != null && p95 > 0) {
      const ratio = rt / p95
      if (ratio <= 0.6)      score += 25  // well below p95
      else if (ratio <= 1.0) score += 22  // normal — at or below p95
      else if (ratio <= 1.5) score += 12  // moderately above p95
      else if (ratio <= 2.5) score += 5   // degraded
      // else: way above p95 → 0 points
    } else if (rt == null) {
      score += 15 // no data — neutral
    } else {
      score += 15 // no p95 baseline yet — neutral
    }
    if (!hasIncident) score += 15

    if (score >= 90)  return 'A'
    if (score >= 75)  return 'B'
    if (score >= 55)  return 'C'
    if (score >= 35)  return 'D'
    return 'F'
  }

  function setFlapping(monitorId) {
    const monitor = monitors.value.find(m => m.id === monitorId)
    if (!monitor) return
    monitor._isFlapping = true
    clearTimeout(flapTimers[monitorId])
    flapTimers[monitorId] = setTimeout(() => {
      const m = monitors.value.find(m => m.id === monitorId)
      if (m) m._isFlapping = false
      delete flapTimers[monitorId]
    }, FLAP_TTL_MS)
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
      const prevStatus = monitor._lastStatus
      monitor._lastStatus          = event.status
      monitor._lastCheckedAt       = event.checked_at
      // Flash animation on status change
      if (prevStatus && prevStatus !== event.status) {
        monitor._wsFlash = event.status === 'up' ? 'up' : 'down'
        setTimeout(() => { monitor._wsFlash = null }, 1600)
      }
      monitor._lastResponseTimeMs  = event.response_time_ms ?? monitor._lastResponseTimeMs
      if (event.response_time_ms != null) {
        const spark = [...(monitor._sparkline || [])]
        spark.push(Math.round(event.response_time_ms * 10) / 10)
        if (spark.length > 20) spark.shift()
        monitor._sparkline = spark
      }
      // Recalculate health score on new check result
      monitor._healthScore = _computeHealth({
        uptime_24h:           monitor._uptime24h,
        has_open_incident:    monitor._hasOpenIncident,
        last_response_time_ms: event.response_time_ms ?? monitor._lastResponseTimeMs,
        p95_response_time_ms: monitor._p95ResponseTimeMs,
      })
    }
  }

  return { monitors, loading, fetchAll, create, update, remove, applyCheckResult, setFlapping }
})
