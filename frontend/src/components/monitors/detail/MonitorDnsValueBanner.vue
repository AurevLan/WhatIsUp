<template>
  <!-- DNS: current resolved value banner -->
  <div class="card mb-6 flex flex-wrap items-center gap-4">
    <div class="flex items-center gap-2 shrink-0">
      <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">{{ monitor.dns_record_type || 'A' }}</span>
      <span class="text-xs text-gray-600">·</span>
      <span class="text-xs font-mono text-gray-400">{{ formatTarget(monitor) }}</span>
    </div>
    <div class="flex-1 min-w-0">
      <template v-if="state.currentValues.value">
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="v in state.currentValues.value" :key="v"
            class="font-mono text-xs px-2 py-0.5 rounded bg-emerald-900/40 text-emerald-300 border border-emerald-800/60"
          >{{ v }}</span>
        </div>
      </template>
      <span v-else class="text-xs text-gray-500 italic">{{ t('monitor_detail.no_resolution_data') }}</span>
    </div>
    <div v-if="monitor.dns_expected_value" class="shrink-0 text-xs font-mono px-2 py-1 rounded bg-blue-900/30 text-blue-300 border border-blue-800/50">
      {{ t('monitor_detail.expected_value', { value: monitor.dns_expected_value }) }}
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { DnsStateKey } from './injectionKeys'

defineProps({
  monitor: { type: Object, required: true },
  formatTarget: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(DnsStateKey, dnsState).
const state = inject(DnsStateKey)

const { t } = useI18n()
</script>
