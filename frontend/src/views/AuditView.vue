<template>
  <div class="page-body">
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-white">{{ t('audit.title') }}</h1>
      <p class="text-gray-400 mt-1">{{ t('audit.subtitle') }}</p>
    </div>

    <!-- Filters -->
    <div class="flex gap-3 mb-6 flex-wrap">
      <select v-model="filterType" @change="load" class="input text-sm">
        <option value="">{{ t('audit.filter_all') }}</option>
        <option value="monitor">{{ t('audit.filter_monitors') }}</option>
        <option value="probe">{{ t('audit.filter_probes') }}</option>
        <option value="alert_channel">{{ t('audit.filter_alert_channels') }}</option>
      </select>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-sm">
      {{ errorMsg }}
    </div>

    <!-- Table -->
    <div class="card overflow-hidden p-0">
      <!-- Skeleton loader -->
      <div v-if="loading" class="p-4 space-y-3">
        <div v-for="i in 8" :key="i" class="skeleton h-10" style="border-radius:var(--radius-sm)" />
      </div>

      <table v-else class="w-full text-sm">
        <thead class="border-b" style="border-color:var(--border)">
          <tr class="text-left" style="color:var(--text-3)">
            <th class="px-4 py-3">{{ t('audit.col_timestamp') }}</th>
            <th class="px-4 py-3">{{ t('audit.col_action') }}</th>
            <th class="px-4 py-3">{{ t('audit.col_object') }}</th>
            <th class="px-4 py-3">{{ t('audit.col_user') }}</th>
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
            <td colspan="4" class="px-4 py-12 text-center text-gray-500">{{ t('audit.empty') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Diff panel -->
    <div v-if="selected?.diff" class="mt-4 card">
      <h3 class="text-sm font-semibold text-gray-300 mb-3">{{ t('audit.changes') }}</h3>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <div class="text-xs text-gray-500 mb-1">{{ t('audit.before') }}</div>
          <pre class="text-xs text-gray-400 bg-gray-800 rounded p-3 overflow-auto max-h-64">{{ JSON.stringify(selected.diff.before, null, 2) }}</pre>
        </div>
        <div>
          <div class="text-xs text-gray-500 mb-1">{{ t('audit.after') }}</div>
          <pre class="text-xs text-gray-300 bg-gray-800 rounded p-3 overflow-auto max-h-64">{{ JSON.stringify(selected.diff.after, null, 2) }}</pre>
        </div>
      </div>
    </div>

    <!-- Load more -->
    <button v-if="logs.length >= limit" @click="loadMore" class="mt-4 btn-secondary w-full text-sm">
      {{ t('audit.load_more') }}
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'

const { t } = useI18n()

const logs = ref([])
const loading = ref(true)
const selected = ref(null)
const errorMsg = ref(null)
const filterType = ref('')
const limit = ref(100)
const offset = ref(0)

function formatDt(dt) {
  return new Date(dt).toLocaleString()
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
  loading.value = true
  try {
    const params = { limit: limit.value, offset: 0 }
    if (filterType.value) params.object_type = filterType.value
    const { data } = await api.get('/audit/', { params })
    logs.value = data
  } catch (err) {
    showError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    loading.value = false
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
    showError(t('common.error'))
  }
}

onMounted(load)
</script>
