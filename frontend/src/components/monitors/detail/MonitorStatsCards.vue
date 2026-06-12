<template>
  <!-- Stats cards -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
    <div class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.uptime_24h') }}</p>
      <p class="text-2xl font-bold font-display mt-1" :class="uptime24?.uptime_percent >= 99 ? 'text-(--up)' : 'text-(--down)'">
        {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
      </p>
      <UptimeViewSplit :stats="uptime24" />
    </div>
    <div class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.uptime_7d') }}</p>
      <p class="text-2xl font-bold font-display mt-1 text-(--accent)">
        {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
      </p>
      <UptimeViewSplit :stats="uptime7d" />
    </div>
    <div v-if="isDns" class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.changes_detected') }}</p>
      <p class="text-2xl font-bold font-display mt-1" :class="dnsChangelog.length > 0 ? 'text-(--warn)' : 'text-(--up)'">
        {{ dnsChangelog.length }}
      </p>
    </div>
    <div v-else-if="hasResponseTime" class="card text-center">
      <p class="text-xs text-(--text-3)">{{ isNetwork ? t('monitor_detail.avg_latency') : t('monitor_detail.avg_response') }}</p>
      <p class="text-2xl font-bold font-display mt-1 text-(--text-2)">
        {{ uptime24?.avg_response_time_ms ? Math.round(uptime24.avg_response_time_ms) + 'ms' : '—' }}
      </p>
    </div>
    <div v-if="isDns" class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.last_change') }}</p>
      <p class="text-sm font-bold mt-1 text-(--text-2)">
        {{ dnsChangelog[0] ? formatDateShort(dnsChangelog[0].checked_at) : '—' }}
      </p>
    </div>
    <div v-else-if="hasResponseTime" class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.p95_response') }}</p>
      <p class="text-2xl font-bold font-display mt-1 text-(--text-2)">
        {{ uptime24?.p95_response_time_ms ? Math.round(uptime24.p95_response_time_ms) + 'ms' : '—' }}
      </p>
    </div>
    <div v-if="responseTrend && hasResponseTime" class="card text-center">
      <p class="text-xs text-(--text-3)">{{ t('monitor_detail.response_time_trend') }}</p>
      <p class="text-2xl font-bold font-display mt-1" :class="responseTrend.up ? 'text-(--down)' : 'text-(--up)'">
        {{ responseTrend.up ? '↑' : '↓' }} {{ responseTrend.pct }}%
      </p>
      <p class="text-xs text-(--text-3) mt-0.5">{{ t('monitor_detail.vs_prev_6h') }}</p>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import UptimeViewSplit from '../UptimeViewSplit.vue'

defineProps({
  uptime24: { type: Object, default: null },
  uptime7d: { type: Object, default: null },
  isDns: { type: Boolean, default: false },
  isNetwork: { type: Boolean, default: false },
  hasResponseTime: { type: Boolean, default: false },
  dnsChangelog: { type: Array, default: () => [] },
  responseTrend: { type: Object, default: null },
  formatDateShort: { type: Function, required: true },
})

const { t } = useI18n()
</script>
