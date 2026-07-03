// DNS-specific state for MonitorDetailView: changelog, current values,
// baseline accept/reset, drift settings toggles, and the alert-suggestion
// modal that nudges users to add an any_down rule when enabling drift.
//
// Mutates monitor.value directly for the various flag toggles + baselines —
// this matches the existing optimistic UX where the toggle flips immediately
// and rolls back if the API call fails.

import { computed, ref } from 'vue'
import { monitorsApi } from '../api/monitors'
import { useDetectionAlertBridge } from './useDetectionAlertBridge'

function normalizeDnsValue(vals) {
  if (!vals || !vals.length) return null
  return [...vals].sort().join(', ')
}

function dnsValueStr(r) {
  if (r.status !== 'up') return null
  if (r.dns_resolved_values?.length) return r.dns_resolved_values.join(', ')
  return null
}

export function useMonitorDns(monitorRef, resultsRef) {
  // ── Changelog (chronological diff over loaded results)
  // results are DESC (newest first) — compare chronologically (reversed)
  const changelog = computed(() => {
    if (monitorRef.value?.check_type !== 'dns') return []
    const chronological = [...resultsRef.value].reverse()
    const changes = []
    let lastNorm = undefined
    let lastVals = null
    for (const r of chronological) {
      const vals = r.status === 'up' ? r.dns_resolved_values ?? [] : null
      const norm = normalizeDnsValue(vals)
      if (norm !== lastNorm) {
        changes.push({
          checked_at: r.checked_at,
          probe_id: r.probe_id,
          old_value: lastNorm === undefined ? null : lastVals ? lastVals.join(', ') : null,
          new_value: vals ? vals.join(', ') : null,
        })
        lastNorm = norm
        lastVals = vals
      }
    }
    return changes.reverse() // most recent first
  })

  function isValueChange(idx) {
    const slice = resultsRef.value.slice(0, 100)
    if (idx >= slice.length - 1) return false
    const curr = normalizeDnsValue(slice[idx].status === 'up' ? slice[idx].dns_resolved_values : null)
    const prev = normalizeDnsValue(slice[idx + 1].status === 'up' ? slice[idx + 1].dns_resolved_values : null)
    return curr !== prev
  }

  // Most recent successful DNS resolution
  const currentValues = computed(() => {
    const r = resultsRef.value.find((r) => r.status === 'up' && r.dns_resolved_values?.length)
    return r?.dns_resolved_values ?? null
  })

  // ── Baseline (accept/reset)
  const baselineLoading = ref(false)
  const baselineMsg = ref('')

  async function acceptBaseline() {
    if (!monitorRef.value) return
    baselineLoading.value = true
    baselineMsg.value = ''
    try {
      const { data } = await monitorsApi.acceptDnsBaseline(monitorRef.value.id, { skipErrorToast: true })
      monitorRef.value.dns_baseline_ips = data.baseline
      baselineMsg.value = `Baseline updated: ${data.baseline.join(', ')}`
      setTimeout(() => {
        baselineMsg.value = ''
      }, 4000)
    } catch (e) {
      baselineMsg.value = e.response?.data?.detail || 'Error'
    } finally {
      baselineLoading.value = false
    }
  }

  async function resetBaseline(type = 'all') {
    if (!monitorRef.value) return
    baselineLoading.value = true
    baselineMsg.value = ''
    try {
      await monitorsApi.resetDnsBaseline(monitorRef.value.id, type, { skipErrorToast: true })
      if (type === 'internal') {
        monitorRef.value.dns_baseline_ips_internal = null
      } else if (type === 'external') {
        monitorRef.value.dns_baseline_ips_external = null
      } else {
        monitorRef.value.dns_baseline_ips = null
        monitorRef.value.dns_baseline_ips_internal = null
        monitorRef.value.dns_baseline_ips_external = null
      }
      baselineMsg.value = 'Baseline cleared — will re-learn on next check.'
      setTimeout(() => {
        baselineMsg.value = ''
      }, 4000)
    } catch (e) {
      baselineMsg.value = e.response?.data?.detail || 'Error'
    } finally {
      baselineLoading.value = false
    }
  }

  // ── Alert-suggestion bridge (offered when enabling drift without a rule).
  // Shared with other detections via useDetectionAlertBridge — DNS drift wires
  // an `any_down` rule (a drift surfaces as the monitor going down).
  const bridge = useDetectionAlertBridge(monitorRef)
  const { alertModal, alertChannels, alertChannelId, alertCreating, createAlertRule, wired, refreshWired } = bridge

  async function toggleSetting(field) {
    if (!monitorRef.value) return
    const newVal = !monitorRef.value[field]
    monitorRef.value[field] = newVal
    try {
      await monitorsApi.update(monitorRef.value.id, { [field]: newVal })
    } catch {
      monitorRef.value[field] = !newVal
      return
    }
    // When enabling DNS drift alerting, nudge the user to wire a notification.
    if (
      (field === 'dns_drift_alert' || field === 'dns_split_enabled') &&
      newVal &&
      monitorRef.value.dns_drift_alert
    ) {
      await bridge.offerAlert('any_down')
    }
  }

  return {
    // changelog + values
    changelog,
    isValueChange,
    currentValues,
    dnsValueStr,
    // baseline
    baselineLoading,
    baselineMsg,
    acceptBaseline,
    resetBaseline,
    // toggles + alert modal
    alertModal,
    alertChannels,
    alertChannelId,
    alertCreating,
    toggleSetting,
    createAlertRule,
    // detection ↔ notification state (B-3)
    wired,
    refreshWired,
  }
}
