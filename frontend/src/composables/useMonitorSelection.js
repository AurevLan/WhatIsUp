import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../stores/monitors'
import { monitorsApi, groupsApi } from '../api/monitors'
import api from '../api/client'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'

/**
 * Multi-selection + bulk / per-row actions for MonitorsView.
 * `monitors` is the full reactive list, `filteredMonitors` the currently
 * visible (filtered) list from useMonitorFilters.
 */
export function useMonitorSelection(monitors, filteredMonitors) {
  const { t } = useI18n()
  const monitorStore = useMonitorStore()
  const { success, error: toastError } = useToast()
  const { confirm } = useConfirm()

  // ── Sélection bulk ──────────────────────────────────────────────────────────
  const selectedIds = ref(new Set())

  const allVisibleSelected = computed(() =>
    filteredMonitors.value.length > 0 &&
    filteredMonitors.value.every(m => selectedIds.value.has(m.id))
  )
  const someVisibleSelected = computed(() =>
    !allVisibleSelected.value &&
    filteredMonitors.value.some(m => selectedIds.value.has(m.id))
  )

  function toggleSelect(id) {
    const s = new Set(selectedIds.value)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    selectedIds.value = s
  }

  function toggleSelectAll() {
    if (allVisibleSelected.value) {
      selectedIds.value = new Set()
    } else {
      selectedIds.value = new Set(filteredMonitors.value.map(m => m.id))
    }
  }

  function clearSelection() { selectedIds.value = new Set() }

  // T1-12: groups + tags catalogues for bulk dropdowns. Loaded lazily on first
  // selection to avoid burning a request on page load when nobody multi-selects.
  const availableGroups = ref([])
  const availableTags = ref([])
  let bulkLookupsLoaded = false
  async function ensureBulkLookups() {
    if (bulkLookupsLoaded) return
    bulkLookupsLoaded = true
    try {
      const [g, tg] = await Promise.all([groupsApi.list(), api.get('/tags/')])
      availableGroups.value = g.data
      availableTags.value = tg.data
    } catch {
      bulkLookupsLoaded = false
    }
  }
  watch(() => selectedIds.value.size, (n) => { if (n > 0) ensureBulkLookups() })

  async function onBulkSetGroup(value) {
    const ids = [...selectedIds.value]
    if (!ids.length || !value) return
    const target_group_id = value === '__none__' ? null : value
    try {
      await monitorsApi.bulkAction({ ids, action: 'set_group', target_group_id })
      success(t('monitors.bulk_success_grouped', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    clearSelection()
    monitorStore.fetchAll()
  }

  async function onBulkAddTag(tagId) {
    const ids = [...selectedIds.value]
    if (!ids.length || !tagId) return
    try {
      await monitorsApi.bulkAction({ ids, action: 'add_tags', tag_ids: [tagId] })
      success(t('monitors.bulk_success_tagged', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    clearSelection()
    monitorStore.fetchAll()
  }

  async function bulkEnable() {
    const ids = [...selectedIds.value]
    // Optimistic update
    monitorStore.monitors.forEach(m => { if (ids.includes(m.id)) m.enabled = true })
    try {
      await monitorsApi.bulkAction({ ids, action: 'enable' })
      success(t('monitors.bulk_success_enabled', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    selectedIds.value = new Set()
    monitorStore.fetchAll()
  }

  async function bulkPause() {
    const ids = [...selectedIds.value]
    // Optimistic update
    monitorStore.monitors.forEach(m => { if (ids.includes(m.id)) m.enabled = false })
    try {
      await monitorsApi.bulkAction({ ids, action: 'pause' })
      success(t('monitors.bulk_success_paused', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    selectedIds.value = new Set()
    monitorStore.fetchAll()
  }

  async function confirmBulkDelete() {
    const count = selectedIds.value.size
    const ok = await confirm({
      title: t('monitors.bulk_confirm_delete_title', { count }),
      message: t('monitors.bulk_confirm_delete_message'),
      confirmLabel: t('monitors.bulk_confirm_delete_label', { count }),
    })
    if (!ok) return
    const ids = [...selectedIds.value]
    // Optimistic update
    monitorStore.monitors = monitorStore.monitors.filter(m => !ids.includes(m.id))
    try {
      await monitorsApi.bulkAction({ ids, action: 'delete' })
      success(t('monitors.bulk_success_deleted', { count }))
    } catch { toastError(t('monitors.bulk_error')) }
    selectedIds.value = new Set()
    monitorStore.fetchAll()
  }

  function bulkExportCsv() {
    const selectedMonitors = monitors.value.filter(m => selectedIds.value.has(m.id))
    const header = 'id,name,url,check_type,enabled,last_status,uptime_24h'
    const rows = selectedMonitors.map(m =>
      [
        m.id,
        `"${(m.name || '').replace(/"/g, '""')}"`,
        `"${(m.url || '').replace(/"/g, '""')}"`,
        m.check_type,
        m.enabled,
        m._lastStatus ?? '',
        m._uptime24h ?? '',
      ].join(',')
    )
    const csv = [header, ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `monitors-export-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
    success(t('monitors.bulk_export_success', { count: selectedMonitors.length }))
  }

  // ── Per-row actions (share store/toast/confirm wiring with bulk) ───────────
  async function toggleEnabled(monitor) {
    try {
      await monitorStore.update(monitor.id, { enabled: !monitor.enabled })
      success(t(monitor.enabled ? 'monitors.paused_success' : 'monitors.enabled_success', { name: monitor.name }))
    } catch { toastError(t('monitors.bulk_error')) }
  }

  async function handleDelete(monitor) {
    const ok = await confirm({
      title: t('monitors.confirm_delete_title', { name: monitor.name }),
      message: t('monitors.confirm_delete_message'),
      confirmLabel: t('common.delete'),
    })
    if (!ok) return
    try {
      await monitorStore.remove(monitor.id)
      success(t('monitors.deleted_success', { name: monitor.name }))
    } catch { toastError(t('monitors.bulk_error')) }
  }

  return {
    selectedIds,
    allVisibleSelected,
    someVisibleSelected,
    toggleSelect,
    toggleSelectAll,
    clearSelection,
    availableGroups,
    availableTags,
    onBulkSetGroup,
    onBulkAddTag,
    bulkEnable,
    bulkPause,
    confirmBulkDelete,
    bulkExportCsv,
    toggleEnabled,
    handleDelete,
  }
}
