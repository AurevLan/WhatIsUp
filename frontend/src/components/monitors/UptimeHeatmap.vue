<template>
  <div>
    <div v-if="loading" class="hmap-loading">
      <div class="skeleton" style="height:95px; border-radius:4px;" />
    </div>
    <div v-else-if="error" class="hmap-error">{{ error }}</div>
    <div v-else class="hmap">
      <div class="hmap__months">
        <span v-for="m in monthLabels" :key="m.key" :style="`left:${m.left}px`" class="hmap__month-label">{{ m.label }}</span>
      </div>
      <div class="hmap__grid">
        <div v-for="(week, wi) in weeks" :key="wi" class="hmap__week">
          <div
            v-for="(day, di) in week"
            :key="di"
            class="hmap__cell"
            :class="day ? `hmap__cell--${day.grade}` : 'hmap__cell--empty'"
            :title="day ? `${day.date} — ${day.uptime != null ? day.uptime.toFixed(1) + '%' : t('heatmap.no_data')}` : ''"
          />
        </div>
      </div>
      <div class="hmap__legend">
        <span class="hmap__data-count">{{ dataCount }} {{ t('common.days') }}</span>
        <span class="hmap__legend-label">{{ t('heatmap.less') }}</span>
        <span class="hmap__cell hmap__cell--none" />
        <span class="hmap__cell hmap__cell--low" />
        <span class="hmap__cell hmap__cell--mid" />
        <span class="hmap__cell hmap__cell--high" />
        <span class="hmap__cell hmap__cell--up" />
        <span class="hmap__legend-label">{{ t('heatmap.more') }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api/client'

const props = defineProps({ monitorId: { type: String, required: true } })
const { locale, t } = useI18n()

const history = ref([])
const loading = ref(true)
const error = ref(null)

onMounted(async () => {
  try {
    const { data } = await api.get(`/monitors/${props.monitorId}/history`, { params: { days: 365 } })
    history.value = data
  } catch (e) {
    error.value = e?.response?.data?.detail ?? e?.message ?? 'Error loading history'
  } finally {
    loading.value = false
  }
})

const byDate = computed(() => {
  const m = {}
  for (const e of history.value) m[e.date] = e
  return m
})

const dataCount = computed(() => history.value.length)

function grade(uptime) {
  if (uptime == null) return 'none'
  if (uptime >= 99)  return 'up'
  if (uptime >= 95)  return 'high'
  if (uptime >= 80)  return 'mid'
  if (uptime > 0)    return 'low'
  return 'down'
}

const weeks = computed(() => {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const start = new Date(today)
  start.setDate(today.getDate() - 364)
  start.setDate(start.getDate() - start.getDay())

  const result = []
  let cur = new Date(start)
  while (cur <= today) {
    const week = []
    for (let d = 0; d < 7; d++) {
      const dateStr = cur.toISOString().slice(0, 10)
      const entry = byDate.value[dateStr]
      const uptime = entry?.uptime_percent ?? null
      const isFuture = cur > today
      week.push(isFuture ? null : { date: dateStr, uptime, grade: uptime == null ? 'none' : grade(uptime) })
      cur = new Date(cur)
      cur.setDate(cur.getDate() + 1)
    }
    result.push(week)
  }
  return result
})

const monthLabels = computed(() => {
  const labels = []
  let lastMonth = -1
  weeks.value.forEach((week, wi) => {
    const firstDay = week.find(d => d)
    if (!firstDay) return
    const d = new Date(firstDay.date)
    const m = d.getMonth()
    if (m !== lastMonth) {
      labels.push({
        key: `${wi}-${m}`,
        label: d.toLocaleString(locale.value, { month: 'short' }),
        left: wi * 13,
      })
      lastMonth = m
    }
  })
  return labels
})
</script>

<style scoped>
.hmap-loading { padding: 4px 0; }
.hmap-error { font-size: 11px; color: #f87171; padding: 8px 0; }

.hmap { user-select: none; overflow-x: auto; padding-bottom: 4px; }

.hmap__months {
  position: relative;
  height: 16px;
  margin-bottom: 4px;
  min-width: max-content;
}
.hmap__month-label {
  position: absolute;
  font-size: 10px;
  color: var(--text-3);
  white-space: nowrap;
}

.hmap__grid {
  display: flex;
  gap: 2px;
  min-width: max-content;
}

.hmap__week {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hmap__cell {
  width: 11px;
  height: 11px;
  border-radius: 2px;
  flex-shrink: 0;
}

.hmap__cell--empty  { background: transparent; }
.hmap__cell--none   { background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.04); }
.hmap__cell--up     { background: #22c55e; }
.hmap__cell--high   { background: #86efac; }
.hmap__cell--mid    { background: #fbbf24; }
.hmap__cell--low    { background: #f97316; }
.hmap__cell--down   { background: #ef4444; }

.hmap__legend {
  display: flex;
  align-items: center;
  gap: 3px;
  margin-top: 8px;
  justify-content: flex-end;
}
.hmap__legend-label {
  font-size: 10px;
  color: var(--text-3);
  margin: 0 2px;
}
.hmap__data-count {
  font-size: 10px;
  color: var(--text-3);
  margin-right: auto;
}
</style>
