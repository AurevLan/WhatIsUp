// Incident-tab state for MonitorDetailView: list, timeline layout, per-incident
// updates, post-mortem markdown, and SLA report download.
//
// Lives at the parent (MonitorDetailView) level rather than inside the tab
// component so the RT chart annotations (which read `incidents`) keep working
// even when the tab itself is unmounted.

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { incidentUpdatesApi } from '../api/incidentUpdates'
import { getSlaReport, monitorsApi } from '../api/monitors'

export function useMonitorIncidents(monitorRef, monitorIdRef) {
  const { t } = useI18n()

  // ── Incidents
  const incidents = ref([])
  const incidentError = ref(null)
  const expandedIncident = ref(null)
  const incidentUpdates = ref([])
  const incidentUpdatesLoading = ref(false)
  const newUpdate = ref({ status: 'investigating', message: '', is_public: true })
  const viewMode = ref('timeline')
  const selectedIncidentId = ref(null)

  const selectedIncident = computed(
    () => incidents.value.find((i) => i.id === selectedIncidentId.value) || null,
  )

  const timelineLayout = computed(() => {
    if (!incidents.value.length) return null
    const now = Date.now()
    const starts = incidents.value.map((i) => new Date(i.started_at).getTime())
    const ends = incidents.value.map((i) =>
      i.resolved_at ? new Date(i.resolved_at).getTime() : now,
    )
    const minT = Math.min(...starts)
    const maxT = Math.max(...ends, now)
    const rawSpan = Math.max(maxT - minT, 3600_000) // min 1h span
    const pad = rawSpan * 0.03
    const t0 = minT - pad
    const t1 = maxT + pad
    const total = t1 - t0
    const items = incidents.value.map((inc) => {
      const s = new Date(inc.started_at).getTime()
      const e = inc.resolved_at ? new Date(inc.resolved_at).getTime() : now
      const x = ((s - t0) / total) * 100
      const w = Math.max(((e - s) / total) * 100, 0.8)
      return { id: inc.id, inc, x, w, ongoing: !inc.resolved_at }
    })
    const ticks = []
    const spanDays = total / 86400_000
    const steps = 4
    for (let k = 0; k <= steps; k++) {
      const tick = t0 + (total * k) / steps
      const d = new Date(tick)
      const label =
        spanDays > 2
          ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
          : d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
      ticks.push({ x: (k / steps) * 100, label })
    }
    return { items, ticks }
  })

  function tooltipFor(inc, fmtDateTime) {
    const start = fmtDateTime(inc.started_at)
    if (!inc.resolved_at) return `${t('incidents.ongoing')} — ${start}`
    const end = fmtDateTime(inc.resolved_at)
    const mins = Math.round(inc.duration_seconds / 60)
    return `${start} → ${end} (${mins} min) — ${inc.scope}`
  }

  async function selectIncident(id) {
    selectedIncidentId.value = id
    incidentUpdatesLoading.value = true
    try {
      const { data } = await incidentUpdatesApi.list(id)
      incidentUpdates.value = data
    } finally {
      incidentUpdatesLoading.value = false
    }
  }

  async function toggleIncidentUpdates(incidentId) {
    if (expandedIncident.value === incidentId) {
      expandedIncident.value = null
      return
    }
    expandedIncident.value = incidentId
    incidentUpdatesLoading.value = true
    try {
      const { data } = await incidentUpdatesApi.list(incidentId)
      incidentUpdates.value = data
    } finally {
      incidentUpdatesLoading.value = false
    }
  }

  async function postIncidentUpdate(incidentId) {
    if (!newUpdate.value.message.trim()) return
    try {
      await incidentUpdatesApi.create(incidentId, { ...newUpdate.value })
      newUpdate.value.message = ''
      const { data } = await incidentUpdatesApi.list(incidentId)
      incidentUpdates.value = data
    } catch {
      // ignore
    }
  }

  async function deleteIncidentUpdate(incidentId, updateId) {
    try {
      await incidentUpdatesApi.delete(incidentId, updateId)
      incidentUpdates.value = incidentUpdates.value.filter((u) => u.id !== updateId)
    } catch {
      // ignore
    }
  }

  async function loadIncidents() {
    incidentError.value = null
    try {
      const { data } = await monitorsApi.incidents(monitorIdRef.value, { limit: 20 })
      incidents.value = data
      if (data.length) {
        const preferred = data.find((i) => !i.resolved_at) || data[0]
        if (
          !selectedIncidentId.value ||
          !data.some((i) => i.id === selectedIncidentId.value)
        ) {
          selectIncident(preferred.id)
        }
      } else {
        selectedIncidentId.value = null
      }
    } catch {
      incidents.value = []
      incidentError.value = t('common.error')
      setTimeout(() => {
        incidentError.value = null
      }, 5000)
    }
  }

  function downloadIncidentsCsv() {
    if (!incidents.value.length) return
    const headers = [
      'id',
      'started_at',
      'resolved_at',
      'duration_seconds',
      'scope',
      'affected_probe_ids',
      'dependency_suppressed',
      'group_id',
    ]
    const rows = incidents.value.map((inc) =>
      headers
        .map((h) => {
          const v = inc[h]
          if (v === null || v === undefined) return ''
          if (Array.isArray(v)) return `"${v.join(';')}"`
          return `"${String(v).replace(/"/g, '""')}"`
        })
        .join(','),
    )
    const csv = [headers.join(','), ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `incidents-${monitorIdRef.value}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── Post-mortem
  const postmortem = ref({ open: false, loading: false, content: '', incidentId: null })

  async function openPostmortem(inc) {
    postmortem.value = { open: true, loading: true, content: '', incidentId: inc.id }
    try {
      const { data } = await monitorsApi.getPostmortem(monitorIdRef.value, inc.id)
      postmortem.value.content = data.content
    } catch (e) {
      postmortem.value.content = `Erreur lors de la génération du post-mortem : ${e.response?.data?.detail || e.message}`
    } finally {
      postmortem.value.loading = false
    }
  }

  function downloadPostmortem() {
    if (!postmortem.value.content) return
    const blob = new Blob([postmortem.value.content], { type: 'text/markdown;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `postmortem-${monitorRef.value?.name || 'monitor'}-${postmortem.value.incidentId?.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── SLA report
  const slaFrom = ref('')
  const slaTo = ref('')
  const slaLoading = ref(false)
  const slaResult = ref(null)

  async function downloadSlaReport() {
    if (!slaFrom.value || !monitorRef.value) return
    slaLoading.value = true
    try {
      const from = new Date(slaFrom.value).toISOString()
      const to = slaTo.value ? new Date(slaTo.value + 'T23:59:59').toISOString() : undefined
      slaResult.value = await getSlaReport(monitorRef.value.id, from, to)
      const blob = new Blob([JSON.stringify(slaResult.value, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sla-${monitorRef.value.name}-${slaFrom.value}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      if (import.meta.env.DEV) console.error('SLA report error', e)
    } finally {
      slaLoading.value = false
    }
  }

  return {
    // incidents
    incidents,
    incidentError,
    expandedIncident,
    incidentUpdates,
    incidentUpdatesLoading,
    newUpdate,
    viewMode,
    selectedIncidentId,
    selectedIncident,
    timelineLayout,
    tooltipFor,
    selectIncident,
    toggleIncidentUpdates,
    postIncidentUpdate,
    deleteIncidentUpdate,
    loadIncidents,
    downloadIncidentsCsv,
    // postmortem
    postmortem,
    openPostmortem,
    downloadPostmortem,
    // sla
    slaFrom,
    slaTo,
    slaLoading,
    slaResult,
    downloadSlaReport,
  }
}
