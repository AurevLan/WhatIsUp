// Quick-schedule maintenance modal for MonitorDetailView. Pre-fills a 2-hour
// window starting now with the monitor name in the title, and POSTs through
// maintenanceApi on save.

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

function blankForm() {
  return {
    name: '',
    description: '',
    starts_at: '',
    ends_at: '',
    suppress_alerts: true,
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
      suppress_alerts: true,
    }
    showModal.value = true
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
        suppress_alerts: form.value.suppress_alerts,
      })
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
    createWindow,
  }
}
