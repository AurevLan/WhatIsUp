<template>
  <!-- DNS: resolution history table -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-gray-300">All resolutions</h2>
      <span v-if="monitor.dns_expected_value" class="text-xs text-gray-500 font-mono bg-gray-800 px-2 py-1 rounded">
        expected value: {{ monitor.dns_expected_value }}
      </span>
    </div>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-xs text-gray-500 border-b border-gray-800">
          <th class="pb-2 text-left w-4"></th>
          <th class="pb-2 text-left">Time</th>
          <th class="pb-2 text-left">Probe</th>
          <th class="pb-2 text-left">{{ t('common.status') }}</th>
          <th class="pb-2 text-left">Returned value</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-800">
        <tr v-for="(r, idx) in results.slice(0, 100)" :key="r.id"
          :class="state.isValueChange(idx) ? 'bg-amber-950/20' : ''"
        >
          <!-- Change indicator -->
          <td class="py-2 pr-1">
            <span v-if="state.isValueChange(idx)" class="text-amber-400 text-xs" title="Valeur différente du check précédent">⚡</span>
          </td>
          <td class="py-2 text-gray-400 text-xs whitespace-nowrap">{{ formatDate(r.checked_at) }}</td>
          <td class="py-2 text-xs">
            <span class="font-medium" :style="`color:${probeColor(r.probe_id)}`">
              {{ probeName(r.probe_id) }}
            </span>
          </td>
          <td class="py-2">
            <span class="text-xs font-medium px-2 py-0.5 rounded-full"
              :class="{
                'bg-emerald-900/50 text-emerald-400': r.status === 'up',
                'bg-red-900/50 text-red-400': r.status === 'down',
                'bg-amber-900/50 text-amber-400': r.status === 'timeout',
                'bg-orange-900/50 text-orange-400': r.status === 'error',
              }">
              {{ r.status }}
            </span>
          </td>
          <td class="py-2 text-xs font-mono max-w-xs"
            :title="state.dnsValueStr(r) || r.error_message || ''">
            <span v-if="state.dnsValueStr(r)"
              :class="state.isValueChange(idx) ? 'text-amber-300 font-semibold' : 'text-emerald-400'">
              {{ state.dnsValueStr(r) }}
            </span>
            <span v-else-if="r.error_message" class="text-red-300 truncate block max-w-xs">{{ r.error_message }}</span>
            <span v-else class="text-gray-600">—</span>
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
