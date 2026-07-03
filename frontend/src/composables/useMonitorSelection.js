import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore, markPendingDelete, unmarkPendingDelete } from '../stores/monitors'
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
  const { success, error: toastError, action: toastAction } = useToast()
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
      await monitorsApi.bulkAction({ ids, action: 'set_group', target_group_id }, { skipErrorToast: true })
      success(t('monitors.bulk_success_grouped', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    clearSelection()
    monitorStore.fetchAll()
  }

  async function onBulkAddTag(tagId) {
    const ids = [...selectedIds.value]
    if (!ids.length || !tagId) return
    try {
      await monitorsApi.bulkAction({ ids, action: 'add_tags', tag_ids: [tagId] }, { skipErrorToast: true })
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
      await monitorsApi.bulkAction({ ids, action: 'enable' }, { skipErrorToast: true })
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
      await monitorsApi.bulkAction({ ids, action: 'pause' }, { skipErrorToast: true })
      success(t('monitors.bulk_success_paused', { count: ids.length }))
    } catch { toastError(t('monitors.bulk_error')) }
    selectedIds.value = new Set()
    monitorStore.fetchAll()
  }

  // C4 (bilan 2026-07) — "Undo" toast instead of an immediate delete call.
  // The API call is deferred until the toast's ~6s window elapses; clicking
  // Undo restores the monitors locally and sends nothing to the server. This
  // is intentionally NOT a server-side undo — the delete simply never fires
  // if the user cancels in time, which is the safe way to implement it.
  async function confirmBulkDelete() {
    const count = selectedIds.value.size
    const ok = await confirm({
      title: t('monitors.bulk_confirm_delete_title', { count }),
      message: t('monitors.bulk_confirm_delete_message'),
      confirmLabel: t('monitors.bulk_confirm_delete_label', { count }),
    })
    if (!ok) return
    const ids = [...selectedIds.value]
    // Snapshot the removed monitors (with their original position) so Undo
    // can restore them locally without a server round-trip.
    const removed = monitorStore.monitors
      .map((m, idx) => ({ m, idx }))
      .filter(({ m }) => ids.includes(m.id))

    // Optimistic UI removal — the real delete is deferred to onExpire below.
    // Register the ids as pending so an interleaved fetchAll (Dashboard
    // navigation, Monitors re-mount…) doesn't resurrect them mid-window.
    markPendingDelete(ids)
    monitorStore.monitors = monitorStore.monitors.filter(m => !ids.includes(m.id))
    selectedIds.value = new Set()

    toastAction(t('monitors.bulk_deleted_pending', { count }), {
      label: t('common.undo'),
      duration: 6000,
      onAction: () => {
        unmarkPendingDelete(ids)
        const restored = [...monitorStore.monitors]
        // Dedupe: only re-insert monitors not already present — a fetchAll
        // or WS event during the window may have brought some of them back,
        // and splicing a second copy would duplicate :key ids in the list.
        const present = new Set(restored.map(m => m.id))
        for (const { m, idx } of removed) {
          if (present.has(m.id)) continue
          restored.splice(Math.min(idx, restored.length), 0, m)
        }
        monitorStore.monitors = restored
        success(t('monitors.bulk_delete_undone', { count }))
      },
      onExpire: async () => {
        try {
          await monitorsApi.bulkAction({ ids, action: 'delete' }, { skipErrorToast: true })
          success(t('monitors.bulk_success_deleted', { count }))
        } catch { toastError(t('monitors.bulk_error')) }
        // Window is over either way — release the ids before refreshing so
        // fetchAll reflects the server's actual state (deleted, or still
        // there if the deferred call failed).
        unmarkPendingDelete(ids)
        monitorStore.fetchAll()
      },
    })
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
      await monitorStore.update(monitor.id, { enabled: !monitor.enabled }, { skipErrorToast: true })
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
      await monitorStore.remove(monitor.id, { skipErrorToast: true })
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
