<template>
  <router-link
    :to="`/monitors/${monitor.id}`"
    class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/[.03] transition-colors group"
  >
    <!-- Status dot -->
    <span
      class="w-2 h-2 rounded-full flex-shrink-0"
      :class="dotClass"
    />

    <!-- Name + target -->
    <div class="flex-1 min-w-0">
      <p class="text-sm font-semibold text-gray-200 truncate group-hover:text-white">
        {{ monitor.name }}
      </p>
      <div class="flex items-center gap-1.5 mt-0.5">
        <span class="text-[10px] font-bold font-mono uppercase px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 flex-shrink-0">
          {{ monitor.check_type }}
        </span>
        <span class="text-[11px] font-mono text-gray-600 truncate">{{ target }}</span>
      </div>
    </div>

    <!-- Status badge -->
    <span class="flex-shrink-0 text-[11px] font-bold px-2.5 py-1 rounded-full border" :class="badgeClass">
      {{ statusLabel }}
    </span>

    <!-- Uptime -->
    <div class="flex-shrink-0 w-14 text-right">
      <p class="text-sm font-bold" :class="uptimeColorClass">{{ uptime }}</p>
      <p class="text-[10px] text-gray-600">24h</p>
    </div>

    <!-- Interval -->
    <p class="flex-shrink-0 w-8 text-right text-[11px] text-gray-600">{{ intervalLabel }}</p>
  </router-link>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ monitor: Object })

const statusCfg = {
  up:      { dot: 'bg-emerald-500',                          badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/25', label: 'UP' },
  down:    { dot: 'bg-red-500 shadow-[0_0_6px_#ef4444]',    badge: 'bg-red-500/10 text-red-400 border-red-500/25',             label: 'DOWN' },
  timeout: { dot: 'bg-amber-500',                            badge: 'bg-amber-500/10 text-amber-400 border-amber-500/25',       label: 'TIMEOUT' },
  error:   { dot: 'bg-orange-500',                           badge: 'bg-orange-500/10 text-orange-400 border-orange-500/25',    label: 'ERROR' },
}
const defCfg = { dot: 'bg-gray-700', badge: 'bg-gray-800 text-gray-500 border-gray-700', label: 'NO DATA' }

const cfg = computed(() => statusCfg[props.monitor._lastStatus] ?? defCfg)

const dotClass    = computed(() => cfg.value.dot)
const badgeClass  = computed(() => cfg.value.badge)
const statusLabel = computed(() => cfg.value.label)

const uptime = computed(() => {
  const u = props.monitor._uptime24h
  return u != null ? u.toFixed(1) + '%' : '—'
})

const uptimeColorClass = computed(() => {
  const u = props.monitor._uptime24h
  if (u == null) return 'text-gray-600'
  if (u >= 99)   return 'text-emerald-400'
  if (u >= 90)   return 'text-amber-400'
  return 'text-red-400'
})

const intervalLabel = computed(() => {
  const s = props.monitor.interval_seconds
  return s < 60 ? s + 's' : Math.round(s / 60) + 'm'
})

const target = computed(() => {
  const m = props.monitor
  const raw = m.url?.replace(/^https?:\/\//, '') || ''
  if (m.check_type === 'tcp')  return m.tcp_port  ? `${raw}:${m.tcp_port}`  : raw
  if (m.check_type === 'udp')  return m.udp_port  ? `${raw}:${m.udp_port}`  : raw
  if (m.check_type === 'smtp') return m.smtp_port ? `${raw}:${m.smtp_port}` : raw
  return raw
})
</script>
