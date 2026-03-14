<template>
  <div class="p-8">
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white">Audit Log</h1>
      <p class="text-gray-400 mt-1">History of all changes made in the system</p>
    </div>

    <!-- Filters -->
    <div class="flex gap-3 mb-6 flex-wrap">
      <select v-model="filterType" @change="load" class="input text-sm">
        <option value="">All objects</option>
        <option value="monitor">Monitors</option>
        <option value="probe">Probes</option>
        <option value="alert_channel">Alert channels</option>
      </select>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-sm">
      {{ errorMsg }}
    </div>

    <!-- Table -->
    <div class="card overflow-hidden p-0">
      <table class="w-full text-sm">
        <thead class="border-b border-gray-800">
          <tr class="text-left text-gray-500">
            <th class="px-4 py-3">Timestamp</th>
            <th class="px-4 py-3">Action</th>
            <th class="px-4 py-3">Object</th>
            <th class="px-4 py-3">User</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in logs" :key="entry.id"
            class="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer"
            @click="selected = selected?.id === entry.id ? null : entry">
            <td class="px-4 py-3 text-gray-400 whitespace-nowrap">{{ formatDt(entry.timestamp) }}</td>
            <td class="px-4 py-3">
              <span class="px-2 py-0.5 rounded text-xs font-mono"
                :class="actionClass(entry.action)">
                {{ entry.action }}
              </span>
            </td>
            <td class="px-4 py-3 text-gray-300">
              {{ entry.object_name || entry.object_id || '—' }}
              <span class="text-gray-600 text-xs ml-1">{{ entry.object_type }}</span>
            </td>
            <td class="px-4 py-3 text-gray-400">{{ entry.user_email || 'system' }}</td>
          </tr>
          <tr v-if="logs.length === 0">
            <td colspan="4" class="px-4 py-12 text-center text-gray-500">No audit log entries.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Diff panel -->
    <div v-if="selected?.diff" class="mt-4 card">
      <h3 class="text-sm font-semibold text-gray-300 mb-3">Changes</h3>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="text-xs text-gray-500 mb-1">Before</div>
          <pre class="text-xs text-gray-400 bg-gray-800 rounded p-3 overflow-auto max-h-64">{{ JSON.stringify(selected.diff.before, null, 2) }}</pre>
        </div>
        <div>
          <div class="text-xs text-gray-500 mb-1">After</div>
          <pre class="text-xs text-gray-300 bg-gray-800 rounded p-3 overflow-auto max-h-64">{{ JSON.stringify(selected.diff.after, null, 2) }}</pre>
        </div>
      </div>
    </div>

    <!-- Load more -->
    <button v-if="logs.length >= limit" @click="loadMore" class="mt-4 btn-secondary w-full text-sm">
      Load more
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/client'

const logs = ref([])
const selected = ref(null)
const errorMsg = ref(null)
const filterType = ref('')
const limit = ref(100)
const offset = ref(0)

function formatDt(dt) {
  return new Date(dt).toLocaleString('fr-FR')
}

function actionClass(action) {
  if (action.endsWith('.delete')) return 'bg-red-900/50 text-red-400'
  if (action.endsWith('.create') || action.endsWith('.register')) return 'bg-emerald-900/50 text-emerald-400'
  return 'bg-blue-900/50 text-blue-400'
}

function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = null }, 5000)
}

async function load() {
  offset.value = 0
  try {
    const params = { limit: limit.value, offset: 0 }
    if (filterType.value) params.object_type = filterType.value
    const { data } = await api.get('/audit/', { params })
    logs.value = data
  } catch (err) {
    showError('Failed to load audit logs.')
    console.error(err)
  }
}

async function loadMore() {
  offset.value += limit.value
  try {
    const params = { limit: limit.value, offset: offset.value }
    if (filterType.value) params.object_type = filterType.value
    const { data } = await api.get('/audit/', { params })
    logs.value.push(...data)
  } catch (err) {
    showError('Failed to load more entries.')
  }
}

onMounted(load)
</script>
