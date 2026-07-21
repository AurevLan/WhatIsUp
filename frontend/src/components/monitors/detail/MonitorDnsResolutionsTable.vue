<template>
  <!-- DNS: resolution history table -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('sweep.all_resolutions') }}</h2>
      <span v-if="monitor.dns_expected_value" class="text-xs text-(--text-3) font-mono bg-(--bg-surface-2) px-2 py-1 rounded">
        expected value: {{ monitor.dns_expected_value }}
      </span>
    </div>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-xs text-(--text-3) border-b border-(--border)">
          <th class="pb-2 text-left w-4"></th>
          <th class="pb-2 text-left">{{ t('sweep.time') }}</th>
          <th class="pb-2 text-left">{{ t('sweep.probe') }}</th>
          <th class="pb-2 text-left">{{ t('common.status') }}</th>
          <th class="pb-2 text-left">{{ t('sweep.returned_value') }}</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-(--border)">
        <tr v-for="(r, idx) in results.slice(0, 100)" :key="r.id"
          :class="state.isValueChange(idx) ? 'bg-[color-mix(in_srgb,var(--warn)_20%,transparent)]' : ''"
        >
          <!-- Change indicator -->
          <td class="py-2 pr-1">
            <span v-if="state.isValueChange(idx)" class="text-(--warn) text-xs" :title="t('sweep.value_differs')">⚡</span>
          </td>
          <td class="py-2 text-(--text-2) text-xs whitespace-nowrap">{{ formatDate(r.checked_at) }}</td>
          <td class="py-2 text-xs">
            <span class="font-medium" :style="`color:${probeColor(r.probe_id)}`">
              {{ probeName(r.probe_id) }}
            </span>
          </td>
          <td class="py-2">
            <span class="text-xs font-medium px-2 py-0.5 rounded-full"
              :class="{
                'bg-[color-mix(in_srgb,var(--up)_12%,transparent)] text-(--up)': r.status === 'up',
                'bg-[color-mix(in_srgb,var(--down)_12%,transparent)] text-(--down)': r.status === 'down' || r.status === 'error',
                'bg-[color-mix(in_srgb,var(--warn)_12%,transparent)] text-(--warn)': r.status === 'timeout',
              }">
              {{ r.status }}
            </span>
          </td>
          <td class="py-2 text-xs font-mono max-w-xs"
            :title="state.dnsValueStr(r) || r.error_message || ''">
            <span v-if="state.dnsValueStr(r)"
              :class="state.isValueChange(idx) ? 'text-(--warn) font-semibold' : 'text-(--up)'">
              {{ state.dnsValueStr(r) }}
            </span>
            <span v-else-if="r.error_message" class="text-(--down) truncate block max-w-xs">{{ r.error_message }}</span>
            <span v-else class="text-(--text-3)">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { DnsStateKey } from './injectionKeys'

defineProps({
  monitor: { type: Object, required: true },
  results: { type: Array, required: true },
  formatDate: { type: Function, required: true },
  probeColor: { type: Function, required: true },
  probeName: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(DnsStateKey, dnsState).
const state = inject(DnsStateKey)

const { t } = useI18n()
</script>
