// Generic "detection → notification" bridge (axis B of the design-system plan).
//
// When a user enables a detection (DNS drift, schema drift, …) the detection
// alone sends no notification — a separate AlertRule is required. This bridges
// the gap: after enabling a detection, call offerAlert(condition) to nudge the
// user to wire a notification channel, then createAlertRule() persists it.
//
// Parameterized by the alert `condition` so every detection reuses the same
// flow instead of each one re-implementing (or omitting) its own.

import { ref } from 'vue'
import api from '../api/client'
import { useToast } from './useToast'

export function useDetectionAlertBridge(monitorRef) {
  const { error: toastError } = useToast()

  const alertModal = ref(false)
  const alertChannels = ref([])
  const alertChannelId = ref('')
  const alertCreating = ref(false)
  const pendingCondition = ref(null)
  // null = unknown, true/false = whether a rule with the watched condition exists.
  const wired = ref(null)

  // Persistent state indicator (B-3): is a rule for this condition already wired?
  async function refreshWired(condition) {
    if (!monitorRef.value) return
    try {
      const { data } = await api.get('/alerts/rules')
      wired.value = data.some(
        (r) => r.monitor_id === monitorRef.value.id && r.condition === condition,
      )
    } catch {
      wired.value = null
    }
  }

  // Open the suggestion modal iff: no rule with this condition already exists
  // for the monitor AND at least one alert channel is configured. Silent on
  // failure — the modal simply doesn't appear.
  async function offerAlert(condition) {
    if (!monitorRef.value) return
    try {
      const [chResp, rulesResp] = await Promise.all([
        api.get('/alerts/channels'),
        api.get('/alerts/rules'),
      ])
      const channels = chResp.data
      const hasRule = rulesResp.data.some(
        (r) => r.monitor_id === monitorRef.value.id && r.condition === condition,
      )
      if (!hasRule && channels.length) {
        alertChannels.value = channels
        alertChannelId.value = channels[0].id
        pendingCondition.value = condition
        alertModal.value = true
      }
    } catch {
      // Silent: modal only appears when channels/rules can be fetched.
    }
  }

  async function createAlertRule() {
    if (!alertChannelId.value || !monitorRef.value || !pendingCondition.value) return
    alertCreating.value = true
    try {
      await api.post('/alerts/rules', {
        monitor_id: monitorRef.value.id,
        condition: pendingCondition.value,
        min_duration_seconds: 0,
        channel_ids: [alertChannelId.value],
      })
      wired.value = true
      alertModal.value = false
    } catch (e) {
      toastError(e.response?.data?.detail || 'Error creating the alert rule')
    } finally {
      alertCreating.value = false
    }
  }

  function dismiss() {
    alertModal.value = false
  }

  return {
    alertModal,
    alertChannels,
    alertChannelId,
    alertCreating,
    pendingCondition,
    wired,
    offerAlert,
    createAlertRule,
    refreshWired,
    dismiss,
  }
}
