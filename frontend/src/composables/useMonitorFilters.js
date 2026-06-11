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
  const { state: monitorFilters, reset: resetMonitorFilters } = useFilterPreset('monitors', {
    q: '',
    status: '',
    type: '',
    group: '',
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

  const statusFilters = computed(() => [
    { val: '',       label: t('monitors.all_statuses'), dot: null,             active: 'bg-blue-600/20 border-blue-500/60 text-blue-300' },
    { val: 'up',     label: 'Up',                      dot: 'bg-emerald-400', active: 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400' },
    { val: 'down',   label: 'Down',                    dot: 'bg-red-500',     active: 'bg-red-500/10 border-red-500/40 text-red-400' },
    { val: 'error',  label: 'Error',                   dot: 'bg-orange-500',  active: 'bg-orange-500/10 border-orange-500/40 text-orange-400' },
    { val: 'paused', label: t('status.paused'),         dot: 'bg-gray-500',   active: 'bg-gray-700/60 border-gray-500 text-gray-300' },
  ])

  const hasActiveFilters = computed(() => filterStatus.value || filterType.value || filterGroup.value || search.value)

  const activeFilterCount = computed(() =>
    [filterStatus.value, filterType.value, filterGroup.value].filter(Boolean).length
  )

  function clearFilters() {
    resetMonitorFilters()
    searchInput_.value = ''
  }

  // ── Pagination ─────────────────────────────────────────────────────────────
  const currentPage = ref(1)

  // ── Sorting ────────────────────────────────────────────────────────────────
  const sortKey = ref('status')
  const sortDir = ref('asc')

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
