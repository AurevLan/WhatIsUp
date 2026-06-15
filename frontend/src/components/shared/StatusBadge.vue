<template>
  <span class="status-badge" :class="cfg.badge">
    <span v-if="dot" class="status-badge__dot" :class="cfg.dot" aria-hidden="true" />
    {{ t(cfg.labelKey) }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

// Canonical monitor-status badge (up / down / timeout / error / paused / no data).
// Single source of truth for the status pill — replaces the per-view badgeClass /
// dotClass / statusLabel duplicates and hard-coded English labels.
const props = defineProps({
  status: { type: String, default: null },
  dot: { type: Boolean, default: true },
})

const { t } = useI18n()

const MAP = {
  up:      { badge: 'badge-up',      dot: 'status-badge__dot--up',      labelKey: 'status.up' },
  down:    { badge: 'badge-down',    dot: 'status-badge__dot--down',    labelKey: 'status.down' },
  timeout: { badge: 'badge-timeout', dot: 'status-badge__dot--timeout', labelKey: 'status.timeout' },
  error:   { badge: 'badge-error',   dot: 'status-badge__dot--error',   labelKey: 'status.error' },
  paused:  { badge: 'badge-unknown', dot: 'status-badge__dot--unknown', labelKey: 'status.paused' },
}
const DEF = { badge: 'badge-unknown', dot: 'status-badge__dot--unknown', labelKey: 'status.no_data' }

const cfg = computed(() => MAP[props.status] ?? DEF)
</script>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4em;
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  white-space: nowrap;
  line-height: 1.5;
}
.status-badge__dot {
  width: 0.45em;
  height: 0.45em;
  border-radius: 99px;
  flex-shrink: 0;
}
.status-badge__dot--up      { background: var(--up); }
.status-badge__dot--down    { background: var(--down); }
.status-badge__dot--timeout { background: var(--warn); }
.status-badge__dot--error   { background: var(--error); }
.status-badge__dot--unknown { background: var(--text-3); }
</style>
