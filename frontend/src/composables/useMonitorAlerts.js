// Alert rules list + auto-alert "no rules" banner setup for MonitorDetailView.
//
// loadRules() filters /alerts/rules to those targeting the current monitor —
// the API doesn't expose a per-monitor endpoint, so we filter client-side.
// `rulesLoaded` flips to true even on error so the empty-state banner doesn't
// flash before the request settles.
//
// The auto-alert flow opens a modal pre-checked with all channels and POSTs
// to /alerts/auto-rules/{monitor_id}, which creates one any_down rule per
// channel. The modal lazy-loads channels the first time it opens.

import { ref, watch } from 'vue'
import api from '../api/client'

export function useMonitorAlerts(monitorRef) {
  const rules = ref([])
  const rulesLoaded = ref(false)

  async function loadRules() {
    if (!monitorRef.value) return
    try {
      const { data } = await api.get('/alerts/rules')
      rules.value = data.filter(
        (r) => r.monitor_id && String(r.monitor_id) === String(monitorRef.value.id),
      )
    } catch {
      // Silent: empty rules array on failure.
    }
    rulesLoaded.value = true
  }

  // Auto-alert setup modal (A2 banner)
  const showAutoModal = ref(false)
  const autoChannels = ref([])
  const autoSelectedChannels = ref([])
  const autoCreating = ref(false)

  watch(showAutoModal, async (v) => {
    if (!v) return
    try {
      const { data } = await api.get('/alerts/channels')
      autoChannels.value = data
      autoSelectedChannels.value = data.map((c) => c.id)
    } catch {
      // Silent: modal still opens, just with an empty channel list.
    }
  })

  async function createAutoRules() {
    if (!monitorRef.value || autoSelectedChannels.value.length === 0) return
    autoCreating.value = true
    try {
      await api.post(`/alerts/auto-rules/${monitorRef.value.id}`, null, {
        params: { channel_ids: autoSelectedChannels.value },
      })
      showAutoModal.value = false
      await loadRules()
    } catch {
      // Silent: error already surfaces via the API client's global toast.
    }
    autoCreating.value = false
  }

  return {
    rules,
    rulesLoaded,
    loadRules,
    showAutoModal,
    autoChannels,
    autoSelectedChannels,
    autoCreating,
    createAutoRules,
  }
}
