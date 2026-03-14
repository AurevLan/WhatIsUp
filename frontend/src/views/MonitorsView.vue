<template>
  <div class="p-8 max-w-6xl mx-auto">

    <!-- Header -->
    <div class="flex items-start justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('monitors.title') }}</h1>
        <p class="text-gray-500 mt-1 text-sm">{{ monitors.length }} monitors</p>
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
        Deselect all
      </button>
    </div>

    <!-- Filter bar -->
    <div class="space-y-3 mb-6">
      <!-- Row 1: search + view toggle -->
      <div class="flex gap-3 items-center">
        <div class="relative flex-1 max-w-sm">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          <input v-model="search" class="input pl-9" :placeholder="t('common.search') + '…'" />
        </div>
        <!-- View mode toggle -->
        <div class="flex gap-1 bg-gray-800/60 p-1 rounded-lg border border-gray-700">
          <button @click="viewMode = 'list'"
            :class="viewMode === 'list' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5">
            <List class="w-3.5 h-3.5" /> {{ t('monitors.view_list') }}
          </button>
          <button @click="viewMode = 'board'"
            :class="viewMode === 'board' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'"
            class="px-3 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5">
            <LayoutGrid class="w-3.5 h-3.5" /> {{ t('monitors.view_board') }}
          </button>
        </div>
        <button @click="showCreate = true" class="btn-primary">
          <Plus class="w-4 h-4" />
          {{ t('monitors.add') }}
        </button>
      </div>

      <!-- Row 2: filter chips -->
      <div class="flex flex-wrap gap-2 items-center">
        <!-- Status chips -->
        <div class="flex gap-1">
          <button v-for="s in ['', 'up', 'down', 'error']" :key="s"
            @click="filterStatus = s"
            :class="filterStatus === s
              ? 'bg-blue-600/30 border-blue-500 text-blue-300'
              : 'border-gray-700 text-gray-500 hover:border-gray-600'"
            class="px-2.5 py-1 rounded-lg text-xs border transition-colors">
            <span v-if="s === ''">{{ t('monitors.all_statuses') }}</span>
            <span v-else class="flex items-center gap-1">
              <span class="w-1.5 h-1.5 rounded-full inline-block"
                :class="{'bg-emerald-400': s==='up','bg-red-500': s==='down','bg-orange-500': s==='error'}"/>
              {{ s }}
            </span>
          </button>
        </div>

        <div class="w-px h-4 bg-gray-700" />

        <!-- Type chips -->
        <div class="flex flex-wrap gap-1">
          <button v-for="typ in ['', 'http', 'tcp', 'dns', 'keyword', 'json_path', 'scenario', 'heartbeat']" :key="typ"
            @click="filterType = typ"
            :class="filterType === typ
              ? 'bg-blue-600/30 border-blue-500 text-blue-300'
              : 'border-gray-700 text-gray-500 hover:border-gray-600'"
            class="px-2.5 py-1 rounded-lg text-xs border transition-colors font-mono">
            {{ typ || t('monitors.all_types') }}
          </button>
        </div>

        <!-- Enabled filter -->
        <div class="w-px h-4 bg-gray-700" />
        <div class="flex gap-1">
          <button v-for="e in [{ val: '', label: t('monitors.all_statuses') }, { val: 'true', label: t('common.enabled') }, { val: 'false', label: t('common.disabled') }]" :key="e.val"
            @click="filterEnabled = e.val"
            :class="filterEnabled === e.val
              ? 'bg-blue-600/30 border-blue-500 text-blue-300'
              : 'border-gray-700 text-gray-500 hover:border-gray-600'"
            class="px-2.5 py-1 rounded-lg text-xs border transition-colors">
            {{ e.label }}
          </button>
        </div>

        <!-- Clear filters -->
        <button v-if="filterStatus || filterType || filterEnabled || filterGroup"
          @click="filterStatus=''; filterType=''; filterEnabled=''; filterGroup=''"
          class="text-xs text-gray-600 hover:text-gray-400 ml-auto flex items-center gap-1">
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

      <div v-else-if="filteredMonitors.length === 0" class="flex flex-col items-center py-16 text-center p-8">
        <Monitor class="w-10 h-10 text-gray-700 mb-3" />
        <p class="text-gray-500 text-sm">{{ t('monitors.no_results') }}</p>
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
            <th class="th">{{ t('common.name') }}</th>
            <th class="th hidden md:table-cell">Target</th>
            <th class="th hidden lg:table-cell">Interval</th>
            <th class="th hidden sm:table-cell">{{ t('monitors.uptime_24h') }}</th>
            <th class="th pr-6 text-right">{{ t('common.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="monitor in filteredMonitors"
            :key="monitor.id"
            class="table-row"
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

            <!-- Actions -->
            <td class="td pr-6">
              <div class="flex items-center justify-end gap-1">
                <router-link :to="`/monitors/${monitor.id}`" class="btn-ghost px-2 py-1 text-xs">
                  <Eye class="w-3.5 h-3.5" />
                </router-link>
                <button @click="toggleEnabled(monitor)" class="btn-ghost px-2 py-1 text-xs" :title="monitor.enabled ? t('monitors.bulk_pause') : t('monitors.bulk_enable')">
                  <Pause v-if="monitor.enabled" class="w-3.5 h-3.5" />
                  <Play v-else class="w-3.5 h-3.5" />
                </button>
                <button @click="confirmDelete(monitor)" class="btn-ghost px-2 py-1 text-xs text-red-500 hover:text-red-400 hover:bg-red-500/10">
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Big Board (mode NOC) -->
    <div v-else class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
      <router-link
        v-for="monitor in filteredMonitors" :key="monitor.id"
        :to="`/monitors/${monitor.id}`"
        class="group relative rounded-xl border p-4 transition-all duration-200 hover:scale-[1.02]"
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

        <!-- Uptime + paused badge -->
        <div class="flex items-end justify-between">
          <div>
            <p class="text-xs text-gray-600">{{ t('monitors.uptime_24h') }}</p>
            <p class="text-base font-bold" :class="uptimeColor(monitor._uptime24h)">
              {{ monitor._uptime24h != null ? monitor._uptime24h.toFixed(1) + '%' : '—' }}
            </p>
          </div>
          <p v-if="!monitor.enabled" class="text-xs text-gray-700 bg-gray-800 px-1.5 py-0.5 rounded">{{ t('status.paused') }}</p>
        </div>
      </router-link>

      <!-- Empty state -->
      <div v-if="filteredMonitors.length === 0"
        class="col-span-full flex flex-col items-center py-16 text-center">
        <Monitor class="w-10 h-10 text-gray-700 mb-3" />
        <p class="text-gray-500 text-sm">{{ t('monitors.no_results') }}</p>
      </div>
    </div>

    <CreateMonitorModal v-if="showCreate" @close="showCreate = false" @created="onCreated" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Download, Eye, LayoutGrid, List, Monitor, Pause, Play, Plus, Search, Trash2, X } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { monitorsApi } from '../api/monitors'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'

const { t } = useI18n()

const monitorStore = useMonitorStore()
const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

const search        = ref('')
const filterEnabled = ref('')
const filterStatus  = ref('')
const filterType    = ref('')
const filterGroup   = ref('')
const viewMode      = ref('list')
const showCreate    = ref(false)

// ── Sélection bulk ────────────────────────────────────────────────────────────
let selectedIds = ref(new Set())

const filteredMonitors = computed(() =>
  monitors.value.filter(m => {
    const q = search.value.toLowerCase()
    const matchSearch  = !q || m.name.toLowerCase().includes(q) || (m.url || '').toLowerCase().includes(q)
    const matchEnabled = !filterEnabled.value || String(m.enabled) === filterEnabled.value
    const matchStatus  = !filterStatus.value  || m._lastStatus === filterStatus.value
    const matchType    = !filterType.value    || m.check_type === filterType.value
    const matchGroup   = !filterGroup.value   || String(m.group_id) === filterGroup.value
    return matchSearch && matchEnabled && matchStatus && matchType && matchGroup
  })
)

// Désélectionner tout quand les filtres changent
watch([search, filterEnabled, filterStatus, filterType, filterGroup], () => {
  selectedIds.value = new Set()
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

async function bulkEnable() {
  const ids = [...selectedIds.value]
  await monitorsApi.bulkAction({ ids, action: 'enable' })
  selectedIds.value = new Set()
  await monitorStore.fetchAll()
}

async function bulkPause() {
  const ids = [...selectedIds.value]
  await monitorsApi.bulkAction({ ids, action: 'pause' })
  selectedIds.value = new Set()
  await monitorStore.fetchAll()
}

async function confirmBulkDelete() {
  const count = selectedIds.value.size
  if (!confirm(t('monitors.bulk_confirm_delete', { count }))) return
  const ids = [...selectedIds.value]
  await monitorsApi.bulkAction({ ids, action: 'delete' })
  selectedIds.value = new Set()
  await monitorStore.fetchAll()
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
  if (monitor.check_type === 'tcp') {
    return monitor.tcp_port ? `${raw}:${monitor.tcp_port}` : raw
  }
  return raw
}

function uptimeColor(u) {
  if (u == null) return 'text-gray-500'
  if (u >= 99)   return 'text-emerald-400'
  if (u >= 90)   return 'text-amber-400'
  return 'text-red-400'
}

async function toggleEnabled(monitor) {
  await monitorStore.update(monitor.id, { enabled: !monitor.enabled })
}

async function confirmDelete(monitor) {
  if (confirm(`Delete "${monitor.name}"?`)) {
    await monitorStore.remove(monitor.id)
  }
}

function onCreated() {
  showCreate.value = false
  monitorStore.fetchAll()
}

onMounted(() => monitorStore.fetchAll())
</script>
