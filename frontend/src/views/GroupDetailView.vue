<template>
  <div class="p-8" v-if="group">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <router-link to="/groups" class="text-gray-400 hover:text-white text-sm">← Groups</router-link>
      <div class="flex-1">
        <h1 class="text-2xl font-bold text-white">{{ group.name }}</h1>
        <p v-if="group.description" class="text-gray-400 text-sm mt-1">{{ group.description }}</p>
      </div>
      <a v-if="group.public_slug" :href="`/status/${group.public_slug}`" target="_blank"
        class="text-xs text-blue-400 hover:underline font-mono">
        /status/{{ group.public_slug }} ↗
      </a>
    </div>

    <!-- Stats -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-gray-500">Monitors</p>
        <p class="text-2xl font-bold mt-1 text-white">{{ monitors.length }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">UP</p>
        <p class="text-2xl font-bold mt-1 text-emerald-400">{{ upCount }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">DOWN / Alerte</p>
        <p class="text-2xl font-bold mt-1 text-red-400">{{ downCount }}</p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">Uptime moy. 24h</p>
        <p class="text-2xl font-bold mt-1 text-blue-400">{{ avgUptime !== null ? avgUptime.toFixed(1) + '%' : '—' }}</p>
      </div>
    </div>

    <!-- Monitors list -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">Monitors du groupe</h2>
        <button @click="showAddMonitor = true" class="text-xs btn-primary">+ Ajouter un monitor</button>
      </div>

      <div v-if="monitors.length === 0" class="text-center text-gray-500 py-8 text-sm">
        Aucun monitor dans ce groupe.
      </div>

      <table v-else class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 border-b border-gray-800">
            <th class="pb-2 text-left">Nom</th>
            <th class="pb-2 text-left">Type</th>
            <th class="pb-2 text-left">URL / Hôte</th>
            <th class="pb-2 text-left">Statut</th>
            <th class="pb-2 text-left">Uptime 24h</th>
            <th class="pb-2"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-800">
          <tr v-for="m in monitors" :key="m.id">
            <td class="py-2">
              <router-link :to="`/monitors/${m.id}`" class="font-medium text-white hover:text-blue-400">
                {{ m.name }}
              </router-link>
            </td>
            <td class="py-2">
              <span class="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-300 font-mono uppercase">
                {{ m.check_type }}
              </span>
            </td>
            <td class="py-2 text-gray-400 text-xs font-mono truncate max-w-xs">
              {{ m.url?.replace(/^https?:\/\//, '') }}
            </td>
            <td class="py-2">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                :class="{
                  'bg-emerald-900/50 text-emerald-400': m.last_status === 'up',
                  'bg-red-900/50 text-red-400': m.last_status === 'down',
                  'bg-amber-900/50 text-amber-400': m.last_status === 'timeout',
                  'bg-orange-900/50 text-orange-400': m.last_status === 'error',
                  'bg-gray-800 text-gray-500': !m.last_status,
                }">
                {{ m.last_status || 'no data' }}
              </span>
            </td>
            <td class="py-2 text-gray-300 text-xs">
              {{ m.uptime_24h != null ? m.uptime_24h.toFixed(1) + '%' : '—' }}
            </td>
            <td class="py-2 text-right">
              <button @click="removeFromGroup(m)" class="text-gray-600 hover:text-red-400 text-xs transition-colors">
                Retirer
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300 mb-4">
      {{ errorMsg }}
    </div>

    <!-- Add monitor modal -->
    <div v-if="showAddMonitor" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-white">Ajouter un monitor</h2>
          <button @click="showAddMonitor = false" class="text-gray-400 hover:text-white">✕</button>
        </div>
        <p class="text-sm text-gray-400 mb-4">Sélectionne un monitor à ajouter à ce groupe.</p>
        <select v-model="selectedMonitorId" class="input w-full mb-4">
          <option value="">-- Choisir un monitor --</option>
          <option v-for="m in availableMonitors" :key="m.id" :value="m.id">
            {{ m.name }} ({{ m.check_type }})
          </option>
        </select>
        <div class="flex gap-3">
          <button @click="showAddMonitor = false" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">
            Annuler
          </button>
          <button @click="addMonitor" :disabled="!selectedMonitorId" class="flex-1 btn-primary">
            Ajouter
          </button>
        </div>
      </div>
    </div>
  </div>
  <div v-else class="p-8 text-gray-400">Chargement…</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { groupsApi, monitorsApi } from '../api/monitors'

const route = useRoute()
const group = ref(null)
const monitors = ref([])
const allMonitors = ref([])
const showAddMonitor = ref(false)
const selectedMonitorId = ref('')
const errorMsg = ref('')

const upCount = computed(() => monitors.value.filter(m => m.last_status === 'up').length)
const downCount = computed(() => monitors.value.filter(m => m.last_status && m.last_status !== 'up').length)
const avgUptime = computed(() => {
  const vals = monitors.value.map(m => m.uptime_24h).filter(v => v != null)
  return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null
})

const availableMonitors = computed(() =>
  allMonitors.value.filter(m => !monitors.value.some(gm => gm.id === m.id))
)

function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = '' }, 5000)
}

async function load() {
  const id = route.params.id
  try {
    const [groupResp, monitorsResp] = await Promise.all([
      groupsApi.get(id),
      monitorsApi.list({ group_id: id }),  // list_monitors enrichit last_status + uptime_24h
    ])
    group.value = groupResp.data
    monitors.value = monitorsResp.data
  } catch (e) {
    showError('Erreur lors du chargement du groupe')
  }
  try {
    const { data } = await monitorsApi.list()
    allMonitors.value = data
  } catch {}
}

async function removeFromGroup(monitor) {
  try {
    await monitorsApi.update(monitor.id, { group_id: null })
    monitors.value = monitors.value.filter(m => m.id !== monitor.id)
  } catch {
    showError('Impossible de retirer le monitor du groupe')
  }
}

async function addMonitor() {
  if (!selectedMonitorId.value) return
  try {
    await monitorsApi.update(selectedMonitorId.value, { group_id: route.params.id })
    showAddMonitor.value = false
    selectedMonitorId.value = ''
    await load()
  } catch {
    showError('Impossible d\'ajouter le monitor au groupe')
  }
}

onMounted(load)
</script>
