<template>
  <div class="p-8 max-w-6xl mx-auto">

    <!-- Header -->
    <div class="flex items-start justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Monitors</h1>
        <p class="text-gray-500 mt-1 text-sm">{{ monitors.length }} monitors configured</p>
      </div>
      <button @click="showCreate = true" class="btn-primary">
        <Plus class="w-4 h-4" />
        New Monitor
      </button>
    </div>

    <!-- Filter bar -->
    <div class="flex gap-3 mb-6">
      <div class="relative flex-1 max-w-xs">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
        <input v-model="search" class="input pl-9" placeholder="Search monitors…" />
      </div>
      <select v-model="filterEnabled" class="input w-auto">
        <option value="">All status</option>
        <option value="true">Enabled</option>
        <option value="false">Paused</option>
      </select>
    </div>

    <!-- Table -->
    <div class="card p-0 overflow-hidden">
      <div v-if="loading" class="p-8">
        <div class="space-y-4">
          <div v-for="i in 5" :key="i" class="h-11 bg-gray-800/50 rounded-xl animate-pulse" />
        </div>
      </div>

      <div v-else-if="filteredMonitors.length === 0" class="flex flex-col items-center py-16 text-center p-8">
        <Monitor class="w-10 h-10 text-gray-700 mb-3" />
        <p class="text-gray-500 text-sm">No monitors match your search</p>
      </div>

      <table v-else class="w-full">
        <thead class="border-b border-gray-800">
          <tr class="px-6">
            <th class="th pl-6">Status</th>
            <th class="th">Name</th>
            <th class="th hidden md:table-cell">URL</th>
            <th class="th hidden lg:table-cell">Interval</th>
            <th class="th hidden sm:table-cell">24h Uptime</th>
            <th class="th pr-6 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="monitor in filteredMonitors"
            :key="monitor.id"
            class="table-row"
          >
            <!-- Status -->
            <td class="td pl-6">
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
              <p v-if="!monitor.enabled" class="text-xs text-gray-600 mt-0.5">Paused</p>
            </td>

            <!-- URL -->
            <td class="td hidden md:table-cell">
              <span class="font-mono text-xs text-gray-500 truncate max-w-[200px] block">{{ monitor.url }}</span>
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
                <button @click="toggleEnabled(monitor)" class="btn-ghost px-2 py-1 text-xs" :title="monitor.enabled ? 'Pause' : 'Enable'">
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

    <CreateMonitorModal v-if="showCreate" @close="showCreate = false" @created="onCreated" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Eye, Monitor, Pause, Play, Plus, Search, Trash2 } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'

const monitorStore = useMonitorStore()
const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

const search = ref('')
const filterEnabled = ref('')
const showCreate = ref(false)

const filteredMonitors = computed(() =>
  monitors.value.filter(m => {
    const q = search.value.toLowerCase()
    const matchSearch = !q || m.name.toLowerCase().includes(q) || m.url.toLowerCase().includes(q)
    const matchEnabled = !filterEnabled.value || String(m.enabled) === filterEnabled.value
    return matchSearch && matchEnabled
  })
)

const statusCfg = {
  up:      { dot: 'bg-emerald-500', badge: 'badge-up',      label: 'Up' },
  down:    { dot: 'bg-red-500',     badge: 'badge-down',    label: 'Down' },
  timeout: { dot: 'bg-amber-500',   badge: 'badge-timeout', label: 'Timeout' },
  error:   { dot: 'bg-orange-500',  badge: 'badge-error',   label: 'Error' },
}
function dotClass(s)   { return statusCfg[s]?.dot   ?? 'bg-gray-600' }
function badgeClass(s) { return statusCfg[s]?.badge  ?? 'badge-unknown' }
function statusLabel(s){ return statusCfg[s]?.label  ?? 'No data' }

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
