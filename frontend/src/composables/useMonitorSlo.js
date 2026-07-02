// SLO panels for MonitorDetailView — covers two independent backend resources:
//
// 1. Legacy SLO/error-budget (`monitor.slo_target` + `monitor.slo_window_days`)
//    served by the GET /monitors/{id}/slo endpoint. Single objective per
//    monitor, no rule list.
//
// 2. V2 Global Health Engine (M4) — `slo_rules` collection with quorum_down /
//    quorum_slow rules and a per-monitor `health_state` snapshot served by
//    GET /monitors/{id}/health-state.
//
// We keep both in a single composable because they render side-by-side in the
// Availability tab and share `monitor.health_engine_enabled`.

import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  createSloRule,
  deleteSloRule,
  getHealthState,
  getSlo,
  listSloRules,
  monitorsApi,
  updateSloRule,
} from '../api/monitors'
import { useToast } from './useToast'

function blankSloForm() {
  return {
    rule_type: 'quorum_down',
    enabled: true,
    quorum_ratio: 0.6,
    window_seconds: 300,
    p95_threshold_ms: 1000,
    min_probes: 2,
    cooldown_seconds: 60,
  }
}

export function useMonitorSlo(monitorRef) {
  const { t } = useI18n()
  const { error: toastError, success: toastSuccess } = useToast()

  // ── Legacy SLO / Error Budget
  const sloData = ref(null)
  const sloEditing = ref(false)
  const sloEditTarget = ref(null)
  const sloEditDays = ref(30)

  async function loadSlo() {
    if (!monitorRef.value || monitorRef.value.slo_target == null) return
    try {
      sloData.value = await getSlo(monitorRef.value.id)
    } catch {
      sloData.value = null
    }
  }

  async function saveSlo() {
    if (!monitorRef.value) return
    await monitorsApi.update(monitorRef.value.id, {
      slo_target: sloEditTarget.value,
      slo_window_days: sloEditDays.value,
    })
    monitorRef.value.slo_target = sloEditTarget.value
    monitorRef.value.slo_window_days = sloEditDays.value
    sloEditing.value = false
    if (sloEditTarget.value != null) await loadSlo()
  }

  // ── V2 Global Health Engine — toggle + SLO CRUD (M4)
  const sloRules = ref([])
  const healthState = ref(null)
  const sloEditor = ref({
    open: false,
    rule: null,
    form: blankSloForm(),
    saving: false,
    error: null,
  })

  async function loadHealthEngine(id) {
    const monitorId = id ?? monitorRef.value?.id
    if (!monitorId) return
    try {
      sloRules.value = await listSloRules(monitorId)
    } catch {
      sloRules.value = []
    }
    try {
      healthState.value = await getHealthState(monitorId)
    } catch {
      healthState.value = null
    }
  }

  const divergentProbes = computed(() => {
    const ph = healthState.value?.probe_health
    if (!ph || typeof ph !== 'object') return []
    return Object.entries(ph)
      .map(([probe_id, v]) => ({ probe_id, score: Number(v?.divergence_score || 0) }))
      .filter((d) => d.score > 0.5)
      .sort((a, b) => b.score - a.score)
  })

  async function toggleHealthEngine(enabled) {
    if (!monitorRef.value) return
    try {
      await monitorsApi.update(monitorRef.value.id, { health_engine_enabled: enabled }, { skipErrorToast: true })
      monitorRef.value.health_engine_enabled = enabled
      toastSuccess(
        enabled
          ? t('monitor_detail.health_engine_enabled_toast')
          : t('monitor_detail.health_engine_disabled_toast'),
      )
    } catch (err) {
      toastError(err?.response?.data?.detail || 'Update failed')
    }
  }

  function openSloEditor(rule = null) {
    sloEditor.value.open = true
    sloEditor.value.rule = rule
    sloEditor.value.error = null
    if (rule) {
      sloEditor.value.form = {
        rule_type: rule.rule_type,
        enabled: rule.enabled,
        quorum_ratio: rule.quorum_ratio ?? 0.6,
        window_seconds: rule.window_seconds ?? 300,
        p95_threshold_ms: rule.p95_threshold_ms ?? 1000,
        min_probes: rule.min_probes ?? 2,
        cooldown_seconds: rule.cooldown_seconds ?? 60,
      }
    } else {
      sloEditor.value.form = blankSloForm()
    }
  }

  async function saveSloRule() {
    if (!monitorRef.value) return
    const f = sloEditor.value.form
    const payload = {
      enabled: f.enabled,
      window_seconds: f.window_seconds,
      min_probes: f.min_probes,
      cooldown_seconds: f.cooldown_seconds,
    }
    if (f.rule_type === 'quorum_down') {
      payload.quorum_ratio = f.quorum_ratio
      payload.p95_threshold_ms = null
    } else if (f.rule_type === 'quorum_slow') {
      payload.p95_threshold_ms = f.p95_threshold_ms
      payload.quorum_ratio = null
    }
    sloEditor.value.saving = true
    sloEditor.value.error = null
    try {
      if (sloEditor.value.rule) {
        await updateSloRule(monitorRef.value.id, sloEditor.value.rule.id, payload)
      } else {
        payload.rule_type = f.rule_type
        await createSloRule(monitorRef.value.id, payload)
      }
      sloEditor.value.open = false
      await loadHealthEngine(monitorRef.value.id)
    } catch (err) {
      sloEditor.value.error = err?.response?.data?.detail || 'Save failed'
    } finally {
      sloEditor.value.saving = false
    }
  }

  async function toggleSloRule(rule) {
    if (!monitorRef.value) return
    try {
      await updateSloRule(monitorRef.value.id, rule.id, { enabled: !rule.enabled }, { skipErrorToast: true })
      await loadHealthEngine(monitorRef.value.id)
    } catch (err) {
      toastError(err?.response?.data?.detail || 'Update failed')
    }
  }

  async function confirmDeleteSloRule(rule) {
    if (!monitorRef.value) return
    if (!confirm(t('monitor_detail.health_engine_confirm_delete'))) return
    try {
      await deleteSloRule(monitorRef.value.id, rule.id, { skipErrorToast: true })
      await loadHealthEngine(monitorRef.value.id)
    } catch (err) {
      toastError(err?.response?.data?.detail || 'Delete failed')
    }
  }

  function formatRuleSummary(rule) {
    if (rule.rule_type === 'quorum_down') {
      const pct = Math.round((rule.quorum_ratio || 0) * 100)
      const win = Math.round((rule.window_seconds || 0) / 60)
      return `≥ ${pct}% probes down · ${win} min · min ${rule.min_probes} probes`
    }
    if (rule.rule_type === 'quorum_slow') {
      const win = Math.round((rule.window_seconds || 0) / 60)
      return `fleet p95 > ${rule.p95_threshold_ms} ms · ${win} min`
    }
    if (rule.rule_type === 'burn_rate') {
      return `burn ≥ ${rule.burn_factor}× · target ${rule.slo_target}`
    }
    return rule.rule_type
  }

  return {
    // legacy
    sloData,
    sloEditing,
    sloEditTarget,
    sloEditDays,
    loadSlo,
    saveSlo,
    // v2 health engine
    sloRules,
    healthState,
    sloEditor,
    divergentProbes,
    loadHealthEngine,
    toggleHealthEngine,
    openSloEditor,
    saveSloRule,
    toggleSloRule,
    confirmDeleteSloRule,
    formatRuleSummary,
  }
}
