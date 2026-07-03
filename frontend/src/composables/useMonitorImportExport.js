import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../stores/monitors'
import { monitorsApi } from '../api/monitors'
import { useToast } from './useToast'

/**
 * JSON export / import of the full monitor list (MonitorsView toolbar).
 * Bind `importFileInput` to the hidden <input type="file">.
 */
export function useMonitorImportExport() {
  const { t } = useI18n()
  const monitorStore = useMonitorStore()
  const { success, error: toastError } = useToast()

  const importFileInput = ref(null)

  async function exportMonitors() {
    try {
      const { data } = await monitorsApi.exportAll({ skipErrorToast: true })
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `monitors-export-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
      success(t('monitors.export_json_success'))
    } catch {
      toastError(t('common.error'))
    }
  }

  function triggerImport() {
    importFileInput.value?.click()
  }

  async function handleImportFile(event) {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const text = await file.text()
      const data = JSON.parse(text)
      if (!Array.isArray(data)) {
        toastError(t('monitors.import_json_invalid'))
        return
      }
      const { data: result } = await monitorsApi.importAll(data, { skipErrorToast: true })
      const parts = []
      if (result.imported > 0) parts.push(`${result.imported} imported`)
      if (result.updated > 0) parts.push(`${result.updated} updated`)
      if (result.errors?.length > 0) parts.push(`${result.errors.length} errors`)
      success(parts.join(', ') || t('common.success'))
      monitorStore.fetchAll()
    } catch {
      toastError(t('monitors.import_json_error'))
    } finally {
      // Reset file input so the same file can be re-selected
      event.target.value = ''
    }
  }

  return { importFileInput, exportMonitors, triggerImport, handleImportFile }
}
