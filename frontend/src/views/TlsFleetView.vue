<template>
  <div class="px-4 sm:px-6 lg:px-8 py-6 max-w-7xl mx-auto">
    <header class="mb-6">
      <h1 class="text-2xl font-bold text-white">{{ t('tls_fleet.title') }}</h1>
      <p class="text-sm text-gray-500 mt-1">{{ t('tls_fleet.subtitle') }}</p>
    </header>

    <!-- Filters -->
    <div class="card mb-4 flex flex-wrap items-end gap-3">
      <div>
        <label class="text-xs text-gray-400 block mb-1">{{ t('tls_fleet.grade_below') }}</label>
        <select v-model="filters.grade_below" @change="reload" class="input text-sm">
          <option value="">—</option>
          <option v-for="g in ['A','B','C','D','E','F']" :key="g" :value="g">{{ g }}</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-gray-400 block mb-1">{{ t('tls_fleet.expires_within') }}</label>
        <input v-model.number="filters.expires_within_days" type="number" min="1" max="365"
               @change="reload" class="input text-sm w-28" placeholder="14" />
      </div>
      <label class="flex items-center gap-2 text-sm text-gray-300">
        <input type="checkbox" v-model="filters.san_mismatch" @change="reload" />
        {{ t('tls_fleet.san_mismatch_only') }}
      </label>
      <div class="ml-auto flex gap-2">
        <button @click="reload" class="btn-ghost text-sm">{{ t('common.refresh') }}</button>
        <button @click="exportCsv" class="btn-primary text-sm">{{ t('tls_fleet.export_csv') }}</button>
      </div>
    </div>

    <!-- Table -->
    <div v-if="loading" class="card text-sm text-gray-500">{{ t('common.loading') }}…</div>
    <div v-else-if="!items.length" class="card text-sm text-gray-500">{{ t('tls_fleet.empty') }}</div>
    <table v-else class="w-full text-sm bg-gray-900/50 border border-gray-800 rounded">
      <thead class="text-xs text-gray-500 uppercase">
        <tr>
          <th class="px-3 py-2 text-left">{{ t('tls_fleet.col_monitor') }}</th>
          <th class="px-3 py-2 text-center">{{ t('tls_fleet.col_grade') }}</th>
          <th class="px-3 py-2 text-left">{{ t('tls_fleet.col_tls') }}</th>
          <th class="px-3 py-2 text-left">{{ t('tls_fleet.col_cipher') }}</th>
          <th class="px-3 py-2 text-center">{{ t('tls_fleet.col_san') }}</th>
          <th class="px-3 py-2 text-right">{{ t('tls_fleet.col_days') }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="it in items" :key="it.monitor_id" class="border-t border-gray-800 hover:bg-gray-800/40">
          <td class="px-3 py-2">
            <router-link :to="`/monitors/${it.monitor_id}`" class="text-blue-400 hover:underline">{{ it.monitor_name }}</router-link>
            <div class="text-xs text-gray-500 font-mono truncate max-w-xs">{{ it.url }}</div>
          </td>
          <td class="px-3 py-2 text-center">
            <span class="px-2 py-0.5 rounded font-bold text-xs" :class="gradeClass(it.grade)">{{ it.grade || '—' }}</span>
          </td>
          <td class="px-3 py-2 text-gray-300">{{ it.tls_version || '—' }}</td>
          <td class="px-3 py-2 text-gray-400 font-mono text-xs">{{ it.cipher_name || '—' }}</td>
          <td class="px-3 py-2 text-center">
            <span v-if="it.san_match" class="text-emerald-400">✓</span>
            <span v-else class="text-red-400">✗</span>
          </td>
          <td class="px-3 py-2 text-right" :class="daysClass(it.days_remaining)">
            {{ it.days_remaining ?? '—' }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { tlsFleetApi } from '../api/tlsFleet'

const { t } = useI18n()
const loading = ref(false)
const items = ref([])
const filters = reactive({ grade_below: '', expires_within_days: null, san_mismatch: false })

const PALETTE = {
  'A+': 'bg-emerald-700/40 text-emerald-300',
  A: 'bg-emerald-800/40 text-emerald-400',
  B: 'bg-yellow-700/40 text-yellow-300',
  C: 'bg-orange-700/40 text-orange-300',
  D: 'bg-red-800/40 text-red-300',
  E: 'bg-red-900/50 text-red-400',
  F: 'bg-red-900/70 text-red-300',
}
function gradeClass(g) { return PALETTE[g] || 'bg-gray-800 text-gray-400' }
function daysClass(d) {
  if (d == null) return 'text-gray-500'
  if (d < 14) return 'text-red-400 font-bold'
  if (d < 30) return 'text-orange-400'
  return 'text-gray-300'
}

async function reload() {
  loading.value = true
  try {
    const params = {}
    if (filters.grade_below) params.grade_below = filters.grade_below
    if (filters.expires_within_days) params.expires_within_days = filters.expires_within_days
    if (filters.san_mismatch) params.san_mismatch = true
    const { data } = await tlsFleetApi.list(params)
    items.value = data.items || []
  } finally { loading.value = false }
}

async function exportCsv() {
  const params = {}
  if (filters.grade_below) params.grade_below = filters.grade_below
  if (filters.expires_within_days) params.expires_within_days = filters.expires_within_days
  if (filters.san_mismatch) params.san_mismatch = true
  const resp = await tlsFleetApi.exportCsv(params)
  const blob = new Blob([resp.data], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'tls-fleet.csv'; a.click()
  URL.revokeObjectURL(url)
}

onMounted(reload)
</script>
