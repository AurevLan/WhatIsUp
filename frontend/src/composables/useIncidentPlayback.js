// V2-02-06 — Stateful "scrubber" for an incident timeline.
//
// Loads /incidents/{id}/timeline once, keeps a sorted list of (probe, status)
// snapshots over time. The consumer drives `cursorMs` (a millisecond offset
// from the incident's window start); the composable returns the per-probe
// state at that exact moment.

import { computed, ref, shallowRef, watch } from 'vue'
import api from '../api/client'

export function useIncidentPlayback(incidentId) {
  const loading = ref(false)
  const error = ref(null)
  const timeline = shallowRef(null)  // raw API response
  const cursorMs = ref(0)            // 0 = window start
  const playing = ref(false)

  let playInterval = null

  async function load() {
    loading.value = true
    error.value = null
    try {
      const { data } = await api.get(`/incidents/${incidentId}/timeline`)
      timeline.value = data
      cursorMs.value = 0
    } catch (e) {
      error.value = e?.response?.data?.detail || String(e)
      timeline.value = null
    } finally {
      loading.value = false
    }
  }

  // Cursor in ms relative to window start; max derived from points span.
  const windowStart = computed(() => {
    if (!timeline.value?.points?.length) return null
    return new Date(timeline.value.points[0].checked_at).getTime()
  })
  const windowEnd = computed(() => {
    const tl = timeline.value
    if (!tl?.points?.length) return null
    return new Date(tl.points[tl.points.length - 1].checked_at).getTime()
  })
  const durationMs = computed(() => {
    if (windowStart.value == null || windowEnd.value == null) return 0
    return Math.max(0, windowEnd.value - windowStart.value)
  })

  const cursorAt = computed(() => {
    if (windowStart.value == null) return null
    return new Date(windowStart.value + cursorMs.value)
  })

  /**
   * For each probe, return the latest sample whose checked_at <= cursor.
   * O(n) per call — acceptable since cap is 2000 points and recompute happens
   * only on cursor change.
   */
  const stateAtCursor = computed(() => {
    const tl = timeline.value
    if (!tl?.points?.length || windowStart.value == null) return new Map()
    const cutoff = windowStart.value + cursorMs.value
    const byProbe = new Map()
    for (const point of tl.points) {
      const t = new Date(point.checked_at).getTime()
      if (t > cutoff) break  // points are sorted asc, we can stop
      byProbe.set(point.probe_id, point)
    }
    return byProbe
  })

  function play(speed = 1) {
    if (playing.value) return
    if (durationMs.value <= 0) return
    playing.value = true
    // Step every 100ms, but advance cursor by 100*speed*N ms so duration is
    // covered in `durationMs / (speed * 30)` real seconds at default speed=1.
    const stepReal = 100
    const stepCursor = (durationMs.value / 30) * speed
    playInterval = setInterval(() => {
      cursorMs.value = Math.min(durationMs.value, cursorMs.value + stepCursor)
      if (cursorMs.value >= durationMs.value) {
        pause()
      }
    }, stepReal)
  }

  function pause() {
    playing.value = false
    if (playInterval) {
      clearInterval(playInterval)
      playInterval = null
    }
  }

  function seek(ms) {
    cursorMs.value = Math.max(0, Math.min(durationMs.value, ms))
  }

  function reset() {
    pause()
    cursorMs.value = 0
  }

  // Auto-pause when component unmounts to avoid leaking the interval —
  // callers should pass cleanup to onUnmounted in their component.
  watch(() => incidentId, () => {
    pause()
    timeline.value = null
    cursorMs.value = 0
  })

  return {
    // state
    loading,
    error,
    timeline,
    cursorMs,
    playing,
    durationMs,
    cursorAt,
    stateAtCursor,
    // actions
    load,
    play,
    pause,
    seek,
    reset,
  }
}
