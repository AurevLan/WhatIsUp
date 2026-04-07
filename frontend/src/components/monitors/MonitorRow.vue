<template>
  <router-link :to="`/monitors/${monitor.id}`" class="monitor-row" :class="wsFlashClass">
    <!-- Status indicator -->
    <span class="monitor-row__dot" :class="dotClass" />

    <!-- Name + target -->
    <div class="monitor-row__info">
      <p class="monitor-row__name">{{ monitor.name }}</p>
      <div class="monitor-row__meta">
        <span class="monitor-row__type">{{ monitor.check_type }}</span>
        <span class="monitor-row__target">{{ target }}</span>
      </div>
    </div>

    <!-- Response time -->
    <span v-if="monitor._lastResponseTimeMs != null" class="monitor-row__rt" :class="responseTimeClass">
      {{ responseTimeLabel }}
    </span>

    <!-- Uptime -->
    <div class="monitor-row__uptime">
      <span class="monitor-row__uptime-val" :class="uptimeColorClass">{{ uptime }}</span>
      <div class="monitor-row__uptime-bar">
        <div class="monitor-row__uptime-fill" :class="uptimeColorClass" :style="`width:${Math.min(100, monitor._uptime24h ?? 0)}%`" />
      </div>
    </div>

    <!-- Flapping indicator -->
    <span v-if="monitor._isFlapping" class="monitor-row__flap" title="Flapping — oscillating rapidly">⚡</span>

    <!-- Health score -->
    <span v-if="monitor._healthScore" class="monitor-row__health" :class="`health--${monitor._healthScore}`">
      {{ monitor._healthScore }}
    </span>

    <!-- Status badge -->
    <span class="monitor-row__badge" :class="badgeClass">{{ statusLabel }}</span>
  </router-link>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  monitor: { type: Object, required: true },
})

const statusCfg = {
  up:      { dot: 'dot--up',      badge: 'badge-up',      label: 'UP' },
  down:    { dot: 'dot--down',    badge: 'badge-down',    label: 'DOWN' },
  timeout: { dot: 'dot--timeout', badge: 'badge-timeout', label: 'TIMEOUT' },
  error:   { dot: 'dot--error',   badge: 'badge-error',   label: 'ERROR' },
}
const defCfg = { dot: 'dot--unknown', badge: 'badge-unknown', label: 'NO DATA' }

const wsFlashClass = computed(() => {
  if (props.monitor._wsFlash === 'up') return 'ws-flash-up'
  if (props.monitor._wsFlash === 'down') return 'ws-flash-down'
  return ''
})
const cfg           = computed(() => statusCfg[props.monitor._lastStatus] ?? defCfg)
const dotClass      = computed(() => cfg.value.dot)
const badgeClass    = computed(() => cfg.value.badge)
const statusLabel   = computed(() => cfg.value.label)

const uptime = computed(() => {
  const u = props.monitor._uptime24h
  return u != null ? u.toFixed(1) + '%' : '—'
})

const uptimeColorClass = computed(() => {
  const u = props.monitor._uptime24h
  if (u == null) return 'text-muted'
  if (u >= 99)   return 'text-up'
  if (u >= 90)   return 'text-warn'
  return 'text-down'
})

const responseTimeLabel = computed(() => {
  const ms = props.monitor._lastResponseTimeMs
  if (ms == null) return null
  return ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(2) + 's'
})

const responseTimeClass = computed(() => {
  const ms = props.monitor._lastResponseTimeMs
  if (ms == null) return 'text-muted'
  const p95 = props.monitor._p95ResponseTimeMs
  if (p95 != null && p95 > 0) {
    const ratio = ms / p95
    if (ratio <= 0.6)  return 'text-up'    // well below p95
    if (ratio <= 1.2)  return 'text-warn'  // near p95
    return 'text-down'                     // above p95
  }
  // Fallback: no p95 data yet → always neutral
  return 'text-muted'
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

<style scoped>
.monitor-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  transition: background .15s;
  cursor: pointer;
  text-decoration: none;
}
.monitor-row:hover { background: rgba(255,255,255,.028); }

/* Status dot */
.monitor-row__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot--up      { background: #34d399; }
.dot--down    { background: #f87171; box-shadow: 0 0 0 0 rgba(248,113,113,.5); animation: pulse-ring 2s ease-out infinite; }
.dot--timeout { background: #fbbf24; }
.dot--error   { background: #fb923c; }
.dot--unknown { background: var(--text-3); }

/* Info */
.monitor-row__info { flex: 1; min-width: 0; }
.monitor-row__name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}
.monitor-row__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.monitor-row__type {
  font-size: 9.5px;
  font-weight: 700;
  font-family: "JetBrains Mono", monospace;
  text-transform: uppercase;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--bg-surface-3);
  color: var(--text-3);
  letter-spacing: .04em;
  flex-shrink: 0;
}
.monitor-row__target {
  font-size: 11px;
  font-family: "JetBrains Mono", monospace;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Response time */
.monitor-row__rt {
  font-size: 11px;
  font-family: "JetBrains Mono", monospace;
  font-weight: 500;
  flex-shrink: 0;
  display: none;
}
@media (min-width: 480px) {
  .monitor-row__rt { display: block; }
}

/* Uptime */
.monitor-row__uptime {
  flex-shrink: 0;
  text-align: right;
  display: none;
}
@media (min-width: 640px) {
  .monitor-row__uptime { display: block; }
}
.monitor-row__uptime-val {
  display: block;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.2;
}
.monitor-row__uptime-bar {
  width: 100%;
  height: 2px;
  background: var(--bg-surface-3);
  border-radius: 1px;
  margin-top: 3px;
  overflow: hidden;
}
.monitor-row__uptime-fill {
  height: 100%;
  border-radius: 1px;
  transition: width .3s ease;
}
.monitor-row__uptime-fill.text-up   { background: #34d399; }
.monitor-row__uptime-fill.text-warn { background: #fbbf24; }
.monitor-row__uptime-fill.text-down { background: #f87171; }
.monitor-row__uptime-fill.text-muted { background: var(--text-3); }

/* Badge */
.monitor-row__badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1.5px 6px;
  border-radius: 99px;
  letter-spacing: .05em;
  text-transform: uppercase;
  border: 1px solid transparent;
  flex-shrink: 0;
}

/* Flapping */
.monitor-row__flap {
  font-size: 11px;
  flex-shrink: 0;
  animation: flap-flash 1.2s ease-in-out infinite;
}
@keyframes flap-flash {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* Health score */
.monitor-row__health {
  font-size: 9.5px;
  font-weight: 800;
  width: 18px;
  height: 18px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  letter-spacing: 0;
}
.health--A { background: rgba(52,211,153,.15); color: #34d399; border: 1px solid rgba(52,211,153,.3); }
.health--B { background: rgba(96,165,250,.15); color: #60a5fa; border: 1px solid rgba(96,165,250,.3); }
.health--C { background: rgba(251,191,36,.15);  color: #fbbf24; border: 1px solid rgba(251,191,36,.3); }
.health--D { background: rgba(251,146,60,.15);  color: #fb923c; border: 1px solid rgba(251,146,60,.3); }
.health--F { background: rgba(248,113,113,.15); color: #f87171; border: 1px solid rgba(248,113,113,.3); }

/* Color utilities */
.text-up   { color: #34d399; }
.text-warn { color: #fbbf24; }
.text-down { color: #f87171; }
.text-muted { color: var(--text-3); }

@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(248,113,113,.5); }
  70%  { box-shadow: 0 0 0 5px rgba(248,113,113,0); }
  100% { box-shadow: 0 0 0 0 rgba(248,113,113,0); }
}
</style>
