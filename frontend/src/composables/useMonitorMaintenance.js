// Quick-schedule suppression modal for MonitorDetailView (plan cap v2, 6d —
// merges the old separate "schedule maintenance" and "silence" flows into
// one). Pre-fills a 2-hour maintenance window starting now with the monitor
// name in the title, offers duration presets, and POSTs through
// maintenanceApi on save. `suppress_alerts` is omitted from the payload here
// on purpose: it only affects group-scoped windows
// (services.maintenance.is_group_maintenance_suppressed), and this modal is
// always monitor-scoped — the API default (true) is a no-op either way.

import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { maintenanceApi } from '../api/maintenance'
import { useToast } from './useToast'

function pad(n) {
  return String(n).padStart(2, '0')
}

function toLocalDateTime(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// Duration presets offered on the quick-schedule modal — credible palliers
// for "I'm touching this, be quiet for a while": half an hour for a quick
// restart, an hour for a routine deploy, four hours for a longer migration,
// and "until tomorrow" for anything open-ended overnight.
export const DURATION_PRESETS = [
  { key: '30m', minutes: 30 },
  { key: '1h', minutes: 60 },
  { key: '4h', minutes: 240 },
  { key: 'tomorrow', minutes: 24 * 60 },
]

function blankForm() {
  return {
    name: '',
    description: '',
    starts_at: '',
    ends_at: '',
    is_maintenance: true,
  }
}

export function useMonitorMaintenance(monitorRef) {
  const { t } = useI18n()
  const { error: toastError, success: toastSuccess } = useToast()

  const showModal = ref(false)
  const saving = ref(false)
  const form = ref(blankForm())

  function openSchedule() {
    const now = new Date()
    const end = new Date(now.getTime() + 2 * 60 * 60 * 1000) // default 2h window
    form.value = {
      name: monitorRef.value ? `${monitorRef.value.name} — maintenance` : '',
      description: '',
      starts_at: toLocalDateTime(now),
      ends_at: toLocalDateTime(end),
      is_maintenance: true,
    }
    showModal.value = true
  }

  function applyPreset(minutes) {
    const start = new Date()
    const end = new Date(start.getTime() + minutes * 60 * 1000)
    form.value.starts_at = toLocalDateTime(start)
    form.value.ends_at = toLocalDateTime(end)
  }

  async function createWindow() {
    if (!form.value.name.trim() || !form.value.starts_at || !form.value.ends_at) {
      toastError(t('maintenance.error_required'))
      return
    }
    saving.value = true
    try {
      await maintenanceApi.create({
        name: form.value.name.trim(),
        description: form.value.description || null,
        monitor_id: monitorRef.value?.id ?? null,
        group_id: null,
        starts_at: new Date(form.value.starts_at).toISOString(),
        ends_at: new Date(form.value.ends_at).toISOString(),
        is_maintenance: form.value.is_maintenance,
      }, { skipErrorToast: true })
      showModal.value = false
      toastSuccess(t('common.success'))
    } catch (err) {
      toastError(t('common.error'))
      if (import.meta.env.DEV) console.error(err)
    } finally {
      saving.value = false
    }
  }

  return {
    showModal,
    saving,
    form,
    openSchedule,
    applyPreset,
    createWindow,
  }
}
