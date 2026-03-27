<template>
  <div>
    <div class="hb__header">
      <span class="hb__label">{{ days }}-day history</span>
      <span class="hb__label">
        Overall: <span :class="overallClass">{{ overallUptime }}%</span>
      </span>
    </div>

    <div class="hb__bars">
      <div
        v-for="bar in paddedBars"
        :key="bar.date"
        class="hb__bar"
        :class="barClass(bar)"
        @mouseenter="hovered = bar"
        @mouseleave="hovered = null"
      >
        <!-- Tooltip -->
        <div v-if="hovered && hovered.date === bar.date" class="hb__tooltip">
          <div class="hb__tooltip-date">{{ formatDate(bar.date) }}</div>
          <div v-if="bar.empty" class="hb__tooltip-muted">No data</div>
          <template v-else>
            <div :class="bar.uptime_percent >= 99 ? 'hb__val--up' : bar.uptime_percent >= 95 ? 'hb__val--warn' : 'hb__val--down'">
              {{ bar.uptime_percent }}% uptime
            </div>
            <div class="hb__tooltip-muted">{{ bar.total }} checks</div>
            <div v-if="bar.avg_response_time_ms" class="hb__tooltip-muted">
              Avg: {{ Math.round(bar.avg_response_time_ms) }}ms
            </div>
          </template>
        </div>
      </div>
    </div>

    <div class="hb__legend">
      <span>{{ days }}d ago</span>
      <span>Today</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  history: { type: Array, default: () => [] },
  days: { type: Number, default: 90 },
})

const { locale } = useI18n()
const hovered = ref(null)

const paddedBars = computed(() => {
  const today = new Date()
  const result = []
  const historyMap = Object.fromEntries(props.history.map(h => [h.date, h]))

  for (let i = props.days - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const dateStr = d.toISOString().slice(0, 10)
    if (historyMap[dateStr]) {
      result.push({ ...historyMap[dateStr], empty: false })
    } else {
      result.push({ date: dateStr, empty: true, uptime_percent: null })
    }
  }
  return result
})

const overallUptime = computed(() => {
  const filled = props.history.filter(h => h.total > 0)
  if (!filled.length) return '—'
  const totalChecks = filled.reduce((s, h) => s + h.total, 0)
  const totalUp = filled.reduce((s, h) => s + h.up_count, 0)
  return totalChecks ? (totalUp / totalChecks * 100).toFixed(2) : '100.00'
})

const overallClass = computed(() => {
  const v = parseFloat(overallUptime.value)
  if (isNaN(v)) return 'hb__val--muted'
  if (v >= 99) return 'hb__val--up'
  if (v >= 95) return 'hb__val--warn'
  return 'hb__val--down'
})

function barClass(bar) {
  if (bar.empty) return 'hb__bar--empty'
  if (bar.uptime_percent >= 99) return 'hb__bar--up'
  if (bar.uptime_percent >= 95) return 'hb__bar--warn'
  return 'hb__bar--down'
}

function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString(locale.value, { day: 'numeric', month: 'short', year: 'numeric' })
}
</script>

<style scoped>
.hb__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.hb__label {
  font-size: 0.75rem;
  color: var(--text-3);
}

.hb__bars {
  display: flex;
  gap: 1px;
  align-items: flex-end;
  height: 32px;
}

.hb__bar {
  flex: 1;
  min-width: 3px;
  border-radius: 2px;
  cursor: pointer;
  position: relative;
  transition: opacity .15s;
}
.hb__bar:hover { opacity: 0.75; }

.hb__bar--empty  { background: var(--bg-surface-3); }
.hb__bar--up     { background: var(--up); }
.hb__bar--warn   { background: var(--warn); }
.hb__bar--down   { background: var(--down); }

.hb__tooltip {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.625rem;
  font-size: 0.75rem;
  white-space: nowrap;
  box-shadow: 0 4px 16px rgba(0,0,0,.4);
  pointer-events: none;
}

.hb__tooltip-date {
  color: var(--text-1);
  font-weight: 600;
  margin-bottom: 2px;
}

.hb__tooltip-muted { color: var(--text-3); }

.hb__val--up   { color: var(--up); }
.hb__val--warn { color: var(--warn); }
.hb__val--down { color: var(--down); }
.hb__val--muted { color: var(--text-3); }

.hb__legend {
  display: flex;
  justify-content: space-between;
  margin-top: 0.25rem;
  font-size: 0.6875rem;
  color: var(--text-3);
}
</style>
