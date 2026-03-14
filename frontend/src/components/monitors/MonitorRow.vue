<template>
  <router-link :to="`/monitors/${monitor.id}`" style="text-decoration:none;">
    <div
      style="display:flex;align-items:center;gap:16px;padding:12px 8px;border-radius:10px;cursor:pointer;transition:background .1s;"
      onmouseenter="this.style.background='rgba(255,255,255,.03)'"
      onmouseleave="this.style.background='transparent'"
    >
      <!-- Dot -->
      <div :style="`width:8px;height:8px;border-radius:50%;flex-shrink:0;background:${dotColor};${monitor._lastStatus==='down'?'box-shadow:0 0 6px '+dotColor:''}`" />

      <!-- Name + URL -->
      <div style="flex:1;min-width:0;">
        <div style="font-size:13px;font-weight:600;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ monitor.name }}</div>
        <div style="display:flex;align-items:center;gap:5px;margin-top:1px;">
          <span style="font-size:10px;font-weight:700;color:#475569;background:#1e293b;padding:1px 5px;border-radius:4px;font-family:monospace;text-transform:uppercase;flex-shrink:0;">{{ monitor.check_type }}</span>
          <span style="font-size:11px;color:#334155;font-family:monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{{ target }}</span>
        </div>
      </div>

      <!-- Badge -->
      <div :style="`display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:700;background:${badgeBg};color:${badgeColor};border:1px solid ${badgeBorder};flex-shrink:0;`">
        {{ statusLabel }}
      </div>

      <!-- Uptime -->
      <div style="text-align:right;flex-shrink:0;width:60px;">
        <div style="font-size:13px;font-weight:700;" :style="{color: uptimeColor}">{{ uptime }}</div>
        <div style="font-size:10px;color:#334155;margin-top:1px;">24h</div>
      </div>

      <!-- Interval -->
      <div style="font-size:11px;color:#334155;flex-shrink:0;width:32px;text-align:right;">{{ intervalLabel }}</div>
    </div>
  </router-link>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ monitor: Object })

const cfg = {
  up:      { dot: '#10b981', bg: 'rgba(16,185,129,.12)',  color: '#34d399', border: 'rgba(16,185,129,.25)', label: 'UP' },
  down:    { dot: '#ef4444', bg: 'rgba(239,68,68,.12)',   color: '#f87171', border: 'rgba(239,68,68,.25)',  label: 'DOWN' },
  timeout: { dot: '#f59e0b', bg: 'rgba(245,158,11,.12)',  color: '#fbbf24', border: 'rgba(245,158,11,.25)', label: 'TIMEOUT' },
  error:   { dot: '#f97316', bg: 'rgba(249,115,22,.12)',  color: '#fb923c', border: 'rgba(249,115,22,.25)', label: 'ERROR' },
}
const def = { dot: '#334155', bg: 'rgba(51,65,85,.2)', color: '#475569', border: 'rgba(51,65,85,.4)', label: 'NO DATA' }

const c = computed(() => cfg[props.monitor._lastStatus] ?? def)
const dotColor    = computed(() => c.value.dot)
const badgeBg     = computed(() => c.value.bg)
const badgeColor  = computed(() => c.value.color)
const badgeBorder = computed(() => c.value.border)
const statusLabel = computed(() => c.value.label)

const uptime = computed(() => {
  const u = props.monitor._uptime24h
  return u != null ? u.toFixed(1) + '%' : '—'
})
const uptimeColor = computed(() => {
  const u = props.monitor._uptime24h
  if (u == null) return '#334155'
  if (u >= 99) return '#34d399'
  if (u >= 90) return '#fbbf24'
  return '#f87171'
})
const intervalLabel = computed(() => {
  const s = props.monitor.interval_seconds
  return s < 60 ? s + 's' : Math.round(s/60) + 'm'
})

const target = computed(() => {
  const m = props.monitor
  const raw = m.url?.replace(/^https?:\/\//, '') || ''
  if (m.check_type === 'tcp') return m.tcp_port ? `${raw}:${m.tcp_port}` : raw
  return raw
})
</script>
