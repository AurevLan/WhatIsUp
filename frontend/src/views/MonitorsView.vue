<template>
  <div class="page-body max-w-6xl">

    <!-- Header -->
    <div class="flex items-start justify-between mb-4">
      <div>
        <h1 class="text-xl font-bold" style="color:var(--text-1)">{{ t('monitors.title') }}</h1>
        <p class="mt-0.5 text-xs" style="color:var(--text-3)">
          {{ monitors.length }} monitors<template v-if="downCount > 0"> — <span style="color:var(--down)">{{ downCount }} down</span></template><template v-if="errorCount > 0">, <span style="color:#fb923c">{{ errorCount }} error</span></template>
        </p>
      </div>
    </div>

    <!-- Barre d'actions contextuelles (bulk) -->
    <div v-if="selectedIds.size > 0"
      class="mb-4 flex flex-wrap items-center gap-3 p-3 rounded-xl bg-blue-950/40 border border-blue-700/50">
      <span class="text-sm text-blue-300 font-medium">{{ selectedIds.size }} selected</span>
      <button @click="bulkEnable" class="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5">
        <Play class="w-3.5 h-3.5" /> {{ t('monitors.bulk_enable') }}
      </button>
      <button @click="bulkPause" class="btn-secondary text-xs flex items-center gap-1.5">
        <Pause class="w-3.5 h-3.5" /> {{ t('monitors.bulk_pause') }}
      </button>
      <button @click="bulkExportCsv" class="btn-secondary text-xs flex items-center gap-1">
        <Download class="w-3.5 h-3.5" /> {{ t('monitors.bulk_export') }}
      </button>
      <button @click="confirmBulkDelete" class="btn-danger text-xs flex items-center gap-1.5">
        <Trash2 class="w-3.5 h-3.5" /> {{ t('monitors.bulk_delete') }}
      </button>
      <button @click="selectedIds.clear(); selectedIds = new Set()" class="ml-auto text-xs text-gray-500 hover:text-gray-300">
        {{ t('monitors.deselect_all') }}
      </button>
    </div>

    <!-- Filter bar -->
    <div class="space-y-1.5 mb-4">
      <!-- Row 1: search + view toggle + add -->
      <div class="flex gap-2 items-center">
        <div class="relative flex-1">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          <input ref="searchInput" :value="searchInput_" @input="onSearchInput($event.target.value)" class="input pl-9 h-8 text-xs" :placeholder="t('common.search') + '…'" />
        </div>
        <div class="flex gap-0.5 bg-gray-800/60 p-0.5 rounded-lg border border-gray-700/80">
          <button @click="setViewMode('list')"
            :class="viewMode === 'list' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-2.5 py-1.5 rounded-md transition-colors" :title="t('monitors.view_list')">
            <List class="w-4 h-4" />
          </button>
          <button @click="setViewMode('board')"
            :class="viewMode === 'board' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-2.5 py-1.5 rounded-md transition-colors" :title="t('monitors.view_board')">
            <LayoutGrid class="w-4 h-4" />
          </button>
        </div>
        <button @click="showCreate = true" class="btn-primary h-8 text-xs">
          <Plus class="w-4 h-4" />
          {{ t('monitors.add') }}
        </button>
      </div>

      <!-- Row 2: filters -->
      <div class="flex flex-wrap gap-2 items-center">
        <!-- Status chips -->
        <div class="flex gap-1">
          <button v-for="s in statusFilters" :key="s.val"
            @click="filterStatus = s.val"
            :class="filterStatus === s.val ? s.active : 'border-gray-700/80 text-gray-500 hover:border-gray-600 hover:text-gray-400'"
            class="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition-colors font-medium">
            <span v-if="s.dot" class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="s.dot" />
            {{ s.label }}
          </button>
        </div>

        <div class="w-px h-4 bg-gray-700/60" />

        <!-- Type dropdown -->
        <select v-model="filterType"
          class="h-7 px-2 pr-6 rounded-lg border border-gray-700/80 bg-gray-900 text-xs text-gray-400 focus:outline-none focus:border-blue-600 transition-colors appearance-none cursor-pointer"
          :class="filterType ? 'border-blue-600/60 text-blue-300' : ''">
          <option value="">{{ t('monitors.all_types') }}</option>
          <option v-for="typ in checkTypes" :key="typ" :value="typ">{{ typ }}</option>
        </select>

        <!-- Active filter count badge -->
        <span v-if="activeFilterCount > 0"
          class="text-xs px-2 py-0.5 rounded-full bg-blue-600/20 border border-blue-500/40 text-blue-300 font-semibold">
          {{ activeFilterCount }} filtre{{ activeFilterCount > 1 ? 's' : '' }}
        </span>

        <!-- Clear -->
        <button v-if="hasActiveFilters"
          @click="clearFilters"
          class="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-400 ml-auto transition-colors">
          <X class="w-3 h-3" /> {{ t('monitors.clear_filters') }}
        </button>
      </div>
    </div>

    <!-- Table (mode liste) -->
    <div v-if="viewMode === 'list'" class="card p-0 overflow-hidden">
      <div v-if="loading" class="p-8">
        <div class="space-y-4">
          <div v-for="i in 5" :key="i" class="h-11 bg-gray-800/50 rounded-xl animate-pulse" />
        </div>
      </div>

      <div v-else-if="filteredMonitors.length === 0" class="empty-state">
        <div class="empty-state__icon"><Monitor :size="22" /></div>
        <p class="empty-state__title">{{ t('monitors.no_results') }}</p>
        <button v-if="hasActiveFilters" @click="clearFilters" class="btn-secondary text-xs mt-3 flex items-center gap-1">
          <X class="w-3 h-3" /> {{ t('monitors.clear_filters') }}
        </button>
      </div>

      <table v-else class="w-full">
        <thead class="border-b border-gray-800">
          <tr class="px-6">
            <th class="th pl-4 w-8">
              <input
                type="checkbox"
                class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 cursor-pointer"
                :checked="allVisibleSelected"
                :indeterminate="someVisibleSelected"
                @change="toggleSelectAll"
              />
            </th>
            <th class="th pl-2">{{ t('common.status') }}</th>
            <th class="th cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('name')">
              <span class="inline-flex items-center gap-0.5">{{ t('common.name') }} <component v-if="isSorted('name')" :is="sortIcon('name')" :size="11" /></span>
            </th>
            <th class="th hidden md:table-cell">Target</th>
            <th class="th hidden lg:table-cell">Interval</th>
            <th class="th hidden sm:table-cell cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('uptime')">
              <span class="inline-flex items-center gap-0.5">{{ t('monitors.uptime_24h') }} <component v-if="isSorted('uptime')" :is="sortIcon('uptime')" :size="11" /></span>
            </th>
            <th class="th hidden lg:table-cell cursor-pointer select-none hover:text-gray-300 transition-colors" @click="setSortKey('rt')">
              <span class="inline-flex items-center gap-0.5">Resp. <component v-if="isSorted('rt')" :is="sortIcon('rt')" :size="11" /></span>
            </th>
            <th class="th hidden lg:table-cell">Trend</th>
            <th class="th pr-6 text-right">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(monitor, idx) in paginatedMonitors"
            :key="monitor.id"
            class="table-row stagger-item group"
            :style="{ animationDelay: idx * 20 + 'ms' }"
            :class="selectedIds.has(monitor.id) ? 'bg-blue-950/20' : ''"
          >
            <!-- Checkbox -->
            <td class="td pl-4 w-8">
              <input
                type="checkbox"
                class="w-4 h-4 rounded border-gray-600 bg-gray-800 text-blue-500 cursor-pointer"
                :checked="selectedIds.has(monitor.id)"
                @change="toggleSelect(monitor.id)"
              />
            </td>

            <!-- Status -->
            <td class="td pl-2">
              <span :class="badgeClass(monitor._lastStatus)">
                <span class="w-1.5 h-1.5 rounded-full" :class="dotClass(monitor._lastStatus)" />
                {{ statusLabel(monitor._lastStatus) }}
              </span>
            </td>

            <!-- Name -->
            <td class="td">
              <router-link :to="`/monitors/${monitor.id}`" class="font-semibold text-gray-200 hover:text-white transition-colors">
                {{ monitor.name }}
              </router-link>
              <p v-if="!monitor.enabled" class="text-xs text-gray-600 mt-0.5">{{ t('status.paused') }}</p>
            </td>

            <!-- Cible -->
            <td class="td hidden md:table-cell">
              <div class="flex items-center gap-2">
                <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono uppercase flex-shrink-0">{{ monitor.check_type }}</span>
                <span class="font-mono text-xs text-gray-500 truncate max-w-[180px]">{{ formatTarget(monitor) }}</span>
              </div>
            </td>

            <!-- Interval -->
            <td class="td hidden lg:table-cell text-gray-500">
              {{ monitor.interval_seconds < 60 ? monitor.interval_seconds + 's' : Math.round(monitor.interval_seconds / 60) + 'm' }}
            </td>

            <!-- Uptime -->
            <td class="td hidden sm:table-cell">
              <span class="font-semibold" :class="uptimeColor(monitor._uptime24h)">
                {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(2) + '%' : '—' }}
              </span>
            </td>

            <!-- Temps de réponse -->
            <td class="td hidden lg:table-cell">
              <span v-if="monitor._lastResponseTimeMs != null" class="font-mono text-xs" :class="responseTimeColor(monitor._lastResponseTimeMs, monitor)">
                {{ monitor._lastResponseTimeMs < 1000
                  ? monitor._lastResponseTimeMs + 'ms'
                  : (monitor._lastResponseTimeMs / 1000).toFixed(2) + 's' }}
              </span>
              <span v-else class="text-gray-700 text-xs">—</span>
            </td>

            <!-- Sparkline -->
            <td class="td hidden lg:table-cell">
              <SparklineCell :data="monitor._sparkline" />
            </td>

            <!-- Actions -->
            <td class="td pr-6">
              <div class="flex items-center justify-end gap-1.5">
                <router-link :to="`/monitors/${monitor.id}`"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-blue-400 hover:bg-blue-500/10 transition-colors"
                  :title="t('common.view')">
                  <Eye class="w-3.5 h-3.5" />
                </router-link>
                <button @click.stop="editingMonitor = monitor"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-400 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
                  :title="t('common.edit')">
                  <PencilLine class="w-3.5 h-3.5" />
                </button>
                <button @click.stop="toggleEnabled(monitor)"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-colors"
                  :class="monitor.enabled
                    ? 'text-gray-400 hover:text-orange-400 hover:bg-orange-500/10'
                    : 'text-emerald-600 hover:text-emerald-400 hover:bg-emerald-500/10'"
                  :title="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')">
                  <Pause v-if="monitor.enabled" class="w-3.5 h-3.5" />
                  <Play v-else class="w-3.5 h-3.5" />
                </button>
                <button @click.stop="handleDelete(monitor)"
                  class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                  :title="t('common.delete')">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination (list mode) -->
      <div v-if="totalPages > 1" class="flex items-center justify-center gap-1 mt-3 px-4 pb-3">
        <button @click="currentPage--" :disabled="currentPage === 1" class="btn-ghost text-xs disabled:opacity-30 px-1.5">←</button>
        <template v-for="p in pageNumbers" :key="p">
          <span v-if="p === '...'" class="text-xs px-1" style="color:var(--text-3)">...</span>
          <button v-else @click="currentPage = p"
            class="text-xs w-7 h-7 rounded flex items-center justify-center transition-colors"
            :class="p === currentPage ? 'font-bold' : 'hover:bg-white/5'"
            :style="p === currentPage ? 'background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border)' : 'color:var(--text-3)'">
            {{ p }}
          </button>
        </template>
        <button @click="currentPage++" :disabled="currentPage === totalPages" class="btn-ghost text-xs disabled:opacity-30 px-1.5">→</button>
      </div>
    </div>

    <!-- Big Board (mode NOC) -->
    <div v-else>
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        <router-link
          v-for="(monitor, idx) in paginatedMonitors" :key="monitor.id"
          :to="`/monitors/${monitor.id}`"
          class="stagger-item group relative rounded-xl border p-4 transition-all duration-200 hover:scale-[1.02]"
          :style="{ animationDelay: idx * 30 + 'ms' }"
          :class="{
            'border-emerald-700/50 bg-emerald-950/20 hover:border-emerald-600': monitor._lastStatus === 'up',
            'border-red-700/60 bg-red-950/30 hover:border-red-600': monitor._lastStatus === 'down',
            'border-amber-700/50 bg-amber-950/20 hover:border-amber-600': monitor._lastStatus === 'timeout',
            'border-orange-700/50 bg-orange-950/20 hover:border-orange-600': monitor._lastStatus === 'error',
            'border-gray-700 bg-gray-900/30 hover:border-gray-600': !monitor._lastStatus,
          }"
        >
          <!-- Status indicator -->
          <div class="flex items-start justify-between mb-3">
            <span class="w-3 h-3 rounded-full mt-0.5 flex-shrink-0"
              :class="{
                'bg-emerald-400 shadow-lg shadow-emerald-500/30': monitor._lastStatus === 'up',
                'bg-red-500 shadow-lg shadow-red-500/40 animate-pulse': monitor._lastStatus === 'down',
                'bg-amber-400': monitor._lastStatus === 'timeout',
                'bg-orange-500': monitor._lastStatus === 'error',
                'bg-gray-600': !monitor._lastStatus,
              }"
            />
            <span class="text-xs font-mono text-gray-600 bg-gray-800/60 px-1.5 py-0.5 rounded uppercase">
              {{ monitor.check_type }}
            </span>
          </div>

          <!-- Name -->
          <p class="text-sm font-semibold text-gray-200 truncate group-hover:text-white mb-1">
            {{ monitor.name }}
          </p>

          <!-- URL (truncated) -->
          <p class="text-xs text-gray-600 truncate font-mono mb-3">
            {{ monitor.url?.replace(/^https?:\/\//, '') || '—' }}
          </p>

          <!-- Uptime + réponse + paused badge -->
          <div class="flex items-end justify-between">
            <div>
              <p class="text-xs text-gray-600">{{ t('monitors.uptime_24h') }}</p>
              <p class="text-base font-bold" :class="uptimeColor(monitor._uptime24h)">
                {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(1) + '%' : '—' }}
              </p>
            </div>
            <div class="text-right">
              <p v-if="monitor._lastResponseTimeMs != null" class="text-xs font-mono" :class="responseTimeColor(monitor._lastResponseTimeMs, monitor)">
                {{ monitor._lastResponseTimeMs < 1000
                  ? monitor._lastResponseTimeMs + 'ms'
                  : (monitor._lastResponseTimeMs / 1000).toFixed(1) + 's' }}
              </p>
              <p v-if="!monitor.enabled" class="text-xs text-gray-700 bg-gray-800 px-1.5 py-0.5 rounded">{{ t('status.paused') }}</p>
            </div>
          </div>

          <!-- Sparkline -->
          <div class="mt-2">
            <SparklineCell :data="monitor._sparkline" />
          </div>

          <!-- Card actions -->
          <div class="mt-3 pt-2 border-t border-gray-700/50 flex items-center justify-end gap-1"
            @click.prevent @mousedown.prevent>
            <button @click.prevent="editingMonitor = monitor"
              class="p-1.5 rounded-md text-gray-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
              :title="t('common.edit')">
              <PencilLine class="w-3.5 h-3.5" />
            </button>
            <button @click.prevent="toggleEnabled(monitor)"
              class="p-1.5 rounded-md transition-colors"
              :class="monitor.enabled
                ? 'text-gray-500 hover:text-orange-400 hover:bg-orange-500/10'
                : 'text-emerald-600 hover:text-emerald-400 hover:bg-emerald-500/10'"
              :title="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')">
              <Pause v-if="monitor.enabled" class="w-3.5 h-3.5" />
              <Play v-else class="w-3.5 h-3.5" />
            </button>
            <button @click.prevent="handleDelete(monitor)"
              class="p-1.5 rounded-md text-gray-600 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              :title="t('common.delete')">
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </router-link>

        <!-- Empty state -->
        <div v-if="filteredMonitors.length === 0" class="col-span-full empty-state">
          <div class="empty-state__icon"><Monitor :size="22" /></div>
          <p class="empty-state__title">{{ t('monitors.no_results') }}</p>
          <button v-if="hasActiveFilters" @click="clearFilters" class="btn-secondary text-xs mt-3 flex items-center gap-1">
            <X class="w-3 h-3" /> {{ t('monitors.clear_filters') }}
          </button>
        </div>
      </div>

      <!-- Pagination (board mode) -->
      <div v-if="totalPages > 1" class="flex items-center justify-center gap-1 mt-3">
        <button @click="currentPage--" :disabled="currentPage === 1" class="btn-ghost text-xs disabled:opacity-30 px-1.5">←</button>
        <template v-for="p in pageNumbers" :key="p">
          <span v-if="p === '...'" class="text-xs px-1" style="color:var(--text-3)">...</span>
          <button v-else @click="currentPage = p"
            class="text-xs w-7 h-7 rounded flex items-center justify-center transition-colors"
            :class="p === currentPage ? 'font-bold' : 'hover:bg-white/5'"
            :style="p === currentPage ? 'background:var(--accent-glow);color:var(--accent);border:1px solid var(--accent-border)' : 'color:var(--text-3)'">
            {{ p }}
          </button>
        </template>
        <button @click="currentPage++" :disabled="currentPage === totalPages" class="btn-ghost text-xs disabled:opacity-30 px-1.5">→</button>
      </div>
    </div>

    <!-- Mobile FAB -->
    <button class="fab" @click="showCreate = true" :title="t('monitors.add')">
      <Plus class="w-6 h-6" />
    </button>

    <CreateMonitorModal v-if="showCreate" @close="showCreate = false" @created="onCreated" />
    <EditMonitorModal v-if="editingMonitor" :monitor="editingMonitor" @close="editingMonitor = null" @updated="onUpdated" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, ChevronUp, Download, Eye, LayoutGrid, List, Monitor, Pause, PencilLine, Play, Plus, Search, Trash2, X } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { monitorsApi } from '../api/monitors'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'
import EditMonitorModal from '../components/monitors/EditMonitorModal.vue'
import SparklineCell from '../components/monitors/SparklineCell.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const monitorStore = useMonitorStore()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()

const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)
const downCount  = computed(() => monitors.value.filter(m => m._lastStatus === 'down').length)
const errorCount = computed(() => monitors.value.filter(m => ['error', 'timeout'].includes(m._lastStatus)).length)

// Initialize from URL query params
const searchInput_  = ref(route.query.q || '')
const search        = ref(route.query.q || '')
let searchTimeout   = null
function onSearchInput(val) {
  searchInput_.value = val
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => { search.value = val }, 200)
}
const filterStatus  = ref(route.query.status || '')
const filterType    = ref(route.query.type || '')
const filterGroup   = ref('')
const showCreate    = ref(false)
const editingMonitor = ref(null)
const searchInput   = ref(null)

// Persist view mode
const STORAGE_KEY = 'whatisup_monitors_view'
const viewMode = ref(localStorage.getItem(STORAGE_KEY) || 'list')
function setViewMode(mode) {
  viewMode.value = mode
  localStorage.setItem(STORAGE_KEY, mode)
}

const checkTypes = ['http', 'tcp', 'udp', 'dns', 'smtp', 'ping', 'keyword', 'json_path', 'scenario', 'heartbeat', 'domain_expiry']

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
  filterStatus.value = ''
  filterType.value   = ''
  filterGroup.value  = ''
  search.value       = ''
  searchInput_.value = ''
}

// ── Pagination ─────────────────────────────────────────────────────────────────
const PAGE_SIZE   = 50
const currentPage = ref(1)

// ── Sorting ────────────────────────────────────────────────────────────────────
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

// ── Sélection bulk ────────────────────────────────────────────────────────────
let selectedIds = ref(new Set())

const STATUS_PRIORITY = { down: 0, error: 1, timeout: 2, up: 3 }

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

// Sync filters to URL
watch([search, filterStatus, filterType], ([q, status, type]) => {
  const query = {}
  if (q) query.q = q
  if (status) query.status = status
  if (type) query.type = type
  router.replace({ query })
  selectedIds.value = new Set()
  currentPage.value = 1
})

// Also reset on group change (no URL)
watch(filterGroup, () => {
  selectedIds.value = new Set()
  currentPage.value = 1
})

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

// ── Keyboard shortcuts ─────────────────────────────────────────────────────────
function onKeydown(e) {
  const tag = e.target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

  if (e.key === '/') {
    e.preventDefault()
    searchInput.value?.focus()
  } else if ((e.key === 'n' || e.key === 'N') && !e.ctrlKey && !e.metaKey) {
    showCreate.value = true
  } else if (e.key === 'Escape') {
    if (showCreate.value) showCreate.value = false
    else if (editingMonitor.value) editingMonitor.value = null
  }
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
  success(`Export CSV de ${selectedMonitors.length} monitor(s) téléchargé`)
}

const statusCfg = {
  up:      { dot: 'bg-emerald-500', badge: 'badge-up',      label: 'Up' },
  down:    { dot: 'bg-red-500',     badge: 'badge-down',    label: 'Down' },
  timeout: { dot: 'bg-amber-500',   badge: 'badge-timeout', label: 'Timeout' },
  error:   { dot: 'bg-orange-500',  badge: 'badge-error',   label: 'Error' },
}
function dotClass(s)    { return statusCfg[s]?.dot   ?? 'bg-gray-600' }
function badgeClass(s)  { return statusCfg[s]?.badge  ?? 'badge-unknown' }
function statusLabel(s) { return statusCfg[s]?.label  ?? 'No data' }

function formatTarget(monitor) {
  const raw = monitor.url?.replace(/^https?:\/\//, '') || ''
  if (monitor.check_type === 'tcp')  return monitor.tcp_port  ? `${raw}:${monitor.tcp_port}`  : raw
  if (monitor.check_type === 'udp')  return monitor.udp_port  ? `${raw}:${monitor.udp_port}`  : raw
  if (monitor.check_type === 'smtp') return monitor.smtp_port ? `${raw}:${monitor.smtp_port}` : raw
  return raw
}

function uptimeColor(u) {
  if (u == null) return 'text-gray-500'
  if (u >= 99)   return 'text-emerald-400'
  if (u >= 90)   return 'text-amber-400'
  return 'text-red-400'
}

function responseTimeColor(ms, monitor) {
  if (ms == null) return 'text-gray-600'
  const p95 = monitor?._p95ResponseTimeMs
  if (p95 != null && p95 > 0) {
    const ratio = ms / p95
    if (ratio <= 0.6)  return 'text-emerald-400'
    if (ratio <= 1.2)  return 'text-amber-400'
    return 'text-red-400'
  }
  return 'text-gray-600'
}

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

function onCreated() {
  showCreate.value = false
  monitorStore.fetchAll()
  success(t('monitors.created_success'))
}

function onUpdated() {
  editingMonitor.value = null
  monitorStore.fetchAll()
  success(t('monitors.updated_success'))
}

onMounted(() => {
  monitorStore.fetchAll()
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
})
</script>
