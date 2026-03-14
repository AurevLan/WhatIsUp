<template>
  <div>
    <div class="flex items-center justify-between mb-2">
      <span class="text-xs text-gray-500">{{ days }}-day history</span>
      <span class="text-xs text-gray-500">
        Overall: <span :class="overallClass">{{ overallUptime }}%</span>
      </span>
    </div>

    <div class="flex gap-px items-end" style="height: 32px;">
      <div
        v-for="bar in paddedBars"
        :key="bar.date"
        class="flex-1 rounded-sm cursor-pointer transition-opacity hover:opacity-80 group relative"
        :class="barClass(bar)"
        style="min-width: 3px;"
        @mouseenter="hovered = bar"
        @mouseleave="hovered = null"
      >
        <!-- Tooltip -->
        <div
          v-if="hovered && hovered.date === bar.date"
          class="absolute bottom-full mb-2 left-1/2 -translate-x-1/2 z-10
                 bg-gray-900 border border-gray-700 rounded-lg p-2 text-xs whitespace-nowrap shadow-xl pointer-events-none"
        >
          <div class="text-gray-300 font-medium">{{ formatDate(bar.date) }}</div>
          <div v-if="bar.empty" class="text-gray-500">No data</div>
          <template v-else>
            <div :class="bar.uptime_percent >= 99 ? 'text-emerald-400' : bar.uptime_percent >= 95 ? 'text-amber-400' : 'text-red-400'">
              {{ bar.uptime_percent }}% uptime
            </div>
            <div class="text-gray-400">{{ bar.total }} checks</div>
            <div v-if="bar.avg_response_time_ms" class="text-gray-400">
              Avg: {{ Math.round(bar.avg_response_time_ms) }}ms
            </div>
          </template>
        </div>
      </div>
    </div>

    <div class="flex justify-between mt-1 text-xs text-gray-600">
      <span>{{ days }}d ago</span>
      <span>Today</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  history: { type: Array, default: () => [] },
  days: { type: Number, default: 90 },
})

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
  if (isNaN(v)) return 'text-gray-400'
  if (v >= 99) return 'text-emerald-400'
  if (v >= 95) return 'text-amber-400'
  return 'text-red-400'
})

function barClass(bar) {
  if (bar.empty) return 'bg-gray-800'
  if (bar.uptime_percent >= 99) return 'bg-emerald-500'
  if (bar.uptime_percent >= 95) return 'bg-amber-400'
  return 'bg-red-500'
}

function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })
}
</script>
