<template>
  <!-- DNS: current resolved value banner -->
  <div class="card mb-6 flex flex-wrap items-center gap-4">
    <div class="flex items-center gap-2 shrink-0">
      <span class="text-xs font-bold text-(--text-2) uppercase tracking-wider">{{ monitor.dns_record_type || 'A' }}</span>
      <span class="text-xs text-(--text-3)">·</span>
      <span class="text-xs font-mono text-(--text-2)">{{ formatTarget(monitor) }}</span>
    </div>
    <div class="flex-1 min-w-0">
      <template v-if="state.currentValues.value">
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="v in state.currentValues.value" :key="v"
            class="font-mono text-xs px-2 py-0.5 rounded bg-[color-mix(in_srgb,var(--up)_12%,transparent)] text-(--up) border border-[color-mix(in_srgb,var(--up)_25%,transparent)]"
          >{{ v }}</span>
        </div>
      </template>
      <span v-else class="text-xs text-(--text-3) italic">{{ t('monitor_detail.no_resolution_data') }}</span>
    </div>
    <div v-if="monitor.dns_expected_value" class="shrink-0 text-xs font-mono px-2 py-1 rounded bg-(--accent-glow) text-(--accent) border border-(--accent-border)">
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
