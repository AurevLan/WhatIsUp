import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDown, ChevronUp } from 'lucide-vue-next'
import { useFilterPreset } from './useFilterPreset'

const PAGE_SIZE = 50
const STATUS_PRIORITY = { down: 0, error: 1, timeout: 2, up: 3 }

// Persist view mode
const STORAGE_KEY = 'whatisup_monitors_view'

const checkTypes = ['http', 'tcp', 'udp', 'dns', 'smtp', 'ping', 'keyword', 'json_path', 'scenario', 'heartbeat', 'domain_expiry']

/**
 * Search / filters / sorting / pagination / view-mode state for MonitorsView.
 * `monitors` is the reactive monitor list (computed over the store).
 */
export function useMonitorFilters(monitors) {
  const { t } = useI18n()

  // Persisted filters (T1-11) — querystring + localStorage, shareable + F5-safe.
  // sortKey/sortDir joined the same preset in C4 (bilan 2026-07) so the sort
  // order survives a reload too. Migration is automatic: useFilterPreset only
  // reads keys present in the stored/URL payload, so legacy presets saved
  // before this change (missing sortKey/sortDir) silently fall back to the
  // defaults below — no explicit migration code needed.
  const { state: monitorFilters, reset: resetMonitorFilters } = useFilterPreset('monitors', {
    q: '',
    status: '',
    type: '',
    group: '',
    sortKey: 'status',
    sortDir: 'asc',
  })
  const searchInput_  = ref(monitorFilters.q || '')
  const search        = computed({
    get: () => monitorFilters.q,
    set: (v) => { monitorFilters.q = v },
  })
  let searchTimeout   = null
  function onSearchInput(val) {
    searchInput_.value = val
    clearTimeout(searchTimeout)
    searchTimeout = setTimeout(() => { search.value = val }, 200)
  }
  const filterStatus  = computed({
    get: () => monitorFilters.status,
    set: (v) => { monitorFilters.status = v },
  })
  const filterType    = computed({
    get: () => monitorFilters.type,
    set: (v) => { monitorFilters.type = v },
  })
  const filterGroup   = computed({
    get: () => monitorFilters.group,
    set: (v) => { monitorFilters.group = v },
  })

  const viewMode = ref(localStorage.getItem(STORAGE_KEY) || 'list')
  function setViewMode(mode) {
    viewMode.value = mode
    localStorage.setItem(STORAGE_KEY, mode)
  }

  // Libellés i18n et couleurs tokenisées : ces chips étaient le dernier îlot
  // de statuts en anglais codés en dur et de couleurs hors design system.
  const statusFilters = computed(() => [
    { val: '',       label: t('monitors.all_statuses'), dot: null,            active: 'bg-(--accent-glow) border-(--accent) text-(--accent)' },
    { val: 'up',     label: t('status.up'),             dot: 'bg-(--up)',     active: 'bg-[color-mix(in_srgb,var(--up)_12%,transparent)] border-(--up) text-(--up)' },
    { val: 'down',   label: t('status.down'),           dot: 'bg-(--down)',   active: 'bg-[color-mix(in_srgb,var(--down)_12%,transparent)] border-(--down) text-(--down)' },
    { val: 'error',  label: t('status.error'),          dot: 'bg-(--error)',  active: 'bg-[color-mix(in_srgb,var(--error)_12%,transparent)] border-(--error) text-(--error)' },
    { val: 'paused', label: t('status.paused'),         dot: 'bg-(--text-3)', active: 'bg-(--bg-surface-2) border-(--border-hover) text-(--text-2)' },
  ])

  const hasActiveFilters = computed(() => filterStatus.value || filterType.value || filterGroup.value || search.value)

  const activeFilterCount = computed(() =>
    [filterStatus.value, filterType.value, filterGroup.value].filter(Boolean).length
  )

  function clearFilters() {
    // sortKey/sortDir live in the same preset for persistence purposes, but
    // the sort order is NOT a filter — "clear filters" must not reset it.
    const keepSortKey = monitorFilters.sortKey
    const keepSortDir = monitorFilters.sortDir
    resetMonitorFilters()
    monitorFilters.sortKey = keepSortKey
    monitorFilters.sortDir = keepSortDir
    searchInput_.value = ''
  }

  // ── Pagination ─────────────────────────────────────────────────────────────
  const currentPage = ref(1)

  // ── Sorting (persisted, C4) ────────────────────────────────────────────────
  const sortKey = computed({
    get: () => monitorFilters.sortKey,
    set: (v) => { monitorFilters.sortKey = v },
  })
  const sortDir = computed({
    get: () => monitorFilters.sortDir,
    set: (v) => { monitorFilters.sortDir = v },
  })

  function setSortKey(key) {
    if (sortKey.value === key) {
      sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortKey.value = key
      sortDir.value = (key === 'uptime' || key === 'rt') ? 'desc' : 'asc'
    }
  }

  function isSorted(key) {
    return sortKey.value === key
  }
  function sortIcon(key) {
    if (sortKey.value !== key) return null
    return sortDir.value === 'asc' ? ChevronUp : ChevronDown
  }

  const filteredMonitors = computed(() => {
    const q = search.value.toLowerCase()
    return monitors.value
      .filter(m => {
        const matchSearch = !q || m.name.toLowerCase().includes(q) || (m.url || '').toLowerCase().includes(q)
        let matchStatus
        if (filterStatus.value === 'paused') {
          matchStatus = !m.enabled
        } else {
          matchStatus = !filterStatus.value || m._lastStatus === filterStatus.value
        }
        const matchType  = !filterType.value  || m.check_type === filterType.value
        const matchGroup = !filterGroup.value || String(m.group_id) === filterGroup.value
        return matchSearch && matchStatus && matchType && matchGroup
      })
      .sort((a, b) => {
        let cmp = 0
        if (sortKey.value === 'status') {
          const pa = STATUS_PRIORITY[a._lastStatus] ?? 4
          const pb = STATUS_PRIORITY[b._lastStatus] ?? 4
          cmp = pa - pb
        } else if (sortKey.value === 'name') {
          cmp = a.name.toLowerCase().localeCompare(b.name.toLowerCase())
        } else if (sortKey.value === 'uptime') {
          const ua = a._uptime24h ?? -1
          const ub = b._uptime24h ?? -1
          cmp = ua - ub
        } else if (sortKey.value === 'rt') {
          const ra = a._lastResponseTimeMs ?? Infinity
          const rb = b._lastResponseTimeMs ?? Infinity
          cmp = ra - rb
        }
        return sortDir.value === 'asc' ? cmp : -cmp
      })
  })

  const totalPages = computed(() => Math.ceil(filteredMonitors.value.length / PAGE_SIZE))

  const pageNumbers = computed(() => {
    const total = totalPages.value
    const cur = currentPage.value
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
    const pages = [1]
    if (cur > 3) pages.push('...')
    for (let i = Math.max(2, cur - 1); i <= Math.min(total - 1, cur + 1); i++) pages.push(i)
    if (cur < total - 2) pages.push('...')
    pages.push(total)
    return pages
  })

  const paginatedMonitors = computed(() =>
    filteredMonitors.value.slice((currentPage.value - 1) * PAGE_SIZE, currentPage.value * PAGE_SIZE)
  )

  // Pagination resets whenever a filter changes (selection clearing is wired
  // by the view, which owns the selection composable).
  // URL / localStorage persistence is handled by useFilterPreset itself.
  watch([search, filterStatus, filterType, filterGroup], () => {
    currentPage.value = 1
  })

  return {
    // search + filters
    searchInput_,
    search,
    onSearchInput,
    filterStatus,
    filterType,
    filterGroup,
    checkTypes,
    statusFilters,
    hasActiveFilters,
    activeFilterCount,
    clearFilters,
    // view mode
    viewMode,
    setViewMode,
    // sorting
    setSortKey,
    isSorted,
    sortIcon,
    // pagination + derived lists
    currentPage,
    totalPages,
    pageNumbers,
    filteredMonitors,
    paginatedMonitors,
  }
}
