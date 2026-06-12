<template>
  <div class="px-4 sm:px-6 lg:px-8 py-6 max-w-7xl mx-auto">
    <header class="mb-6">
      <h1 class="font-display text-2xl font-bold text-(--text-1)">{{ t('tls_fleet.title') }}</h1>
      <p class="text-sm text-(--text-3) mt-1">{{ t('tls_fleet.subtitle') }}</p>
    </header>

    <!-- Filters -->
    <div class="card mb-4 flex flex-wrap items-end gap-3">
      <div>
        <label class="text-xs text-(--text-2) block mb-1">{{ t('tls_fleet.grade_below') }}</label>
        <select v-model="filters.grade_below" @change="reload" class="input text-sm">
          <option value="">—</option>
          <option v-for="g in ['A','B','C','D','E','F']" :key="g" :value="g">{{ g }}</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-(--text-2) block mb-1">{{ t('tls_fleet.expires_within') }}</label>
        <input v-model.number="filters.expires_within_days" type="number" min="1" max="365"
               @change="reload" class="input text-sm w-28" placeholder="14" />
      </div>
      <label class="flex items-center gap-2 text-sm text-(--text-2)">
        <input type="checkbox" v-model="filters.san_mismatch" @change="reload" />
        {{ t('tls_fleet.san_mismatch_only') }}
      </label>
      <div class="ml-auto flex gap-2">
        <button @click="reload" class="btn-ghost text-sm">{{ t('common.refresh') }}</button>
        <button @click="exportCsv" class="btn-primary text-sm">{{ t('tls_fleet.export_csv') }}</button>
      </div>
    </div>

    <!-- Table -->
    <div v-if="loading" class="card text-sm text-(--text-3)">{{ t('common.loading') }}…</div>
    <div v-else-if="!items.length" class="card text-sm text-(--text-3)">{{ t('tls_fleet.empty') }}</div>
    <table v-else class="w-full text-sm bg-(--bg-surface) border border-(--border) rounded">
      <thead class="text-xs text-(--text-3) uppercase">
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
        <tr v-for="it in items" :key="it.monitor_id" class="border-t border-(--border) hover:bg-(--bg-surface-2)">
          <td class="px-3 py-2">
            <router-link :to="`/monitors/${it.monitor_id}`" class="text-(--accent) hover:underline">{{ it.monitor_name }}</router-link>
            <div class="text-xs text-(--text-3) font-mono truncate max-w-xs">{{ it.url }}</div>
          </td>
          <td class="px-3 py-2 text-center">
            <span class="font-display px-2 py-0.5 rounded font-bold text-xs" :class="gradeClass(it.grade)">{{ it.grade || '—' }}</span>
          </td>
          <td class="px-3 py-2 text-(--text-2)">{{ it.tls_version || '—' }}</td>
          <td class="px-3 py-2 text-(--text-2) font-mono text-xs">{{ it.cipher_name || '—' }}</td>
          <td class="px-3 py-2 text-center">
            <span v-if="it.san_match" class="text-(--up)">✓</span>
            <span v-else class="text-(--down)">✗</span>
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
  'A+': 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)',
  A: 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)',
  B: 'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn)',
  C: 'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn)',
  D: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
  E: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
  F: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
}
function gradeClass(g) { return PALETTE[g] || 'bg-(--bg-surface-2) text-(--text-2)' }
function daysClass(d) {
  if (d == null) return 'text-(--text-3)'
  if (d < 14) return 'text-(--down) font-bold'
  if (d < 30) return 'text-(--warn)'
  return 'text-(--text-2)'
}

function buildParams() {
  const params = {}
  if (filters.grade_below) params.grade_below = filters.grade_below
  if (filters.expires_within_days) params.expires_within_days = filters.expires_within_days
  if (filters.san_mismatch) params.san_mismatch = true
  return params
}

async function reload() {
  loading.value = true
  try {
    const { data } = await tlsFleetApi.list(buildParams())
    items.value = data.items || []
  } finally { loading.value = false }
}

async function exportCsv() {
  const resp = await tlsFleetApi.exportCsv(buildParams())
  const blob = new Blob([resp.data], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'tls-fleet.csv'; a.click()
  URL.revokeObjectURL(url)
}

onMounted(reload)
</script>
