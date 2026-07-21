<template>
  <div>
    <!-- Header: title + time range selector -->
    <div class="flex items-center justify-between mb-6 flex-wrap gap-3">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('metrics.title') }}</h2>
      <div class="inline-flex rounded-md border border-(--border) overflow-hidden">
        <button
          v-for="range in TIME_RANGES"
          :key="range.hours"
          @click="setRange(range.hours)"
          class="px-3 py-1.5 text-xs font-medium transition-colors border-r border-(--border) last:border-r-0"
          :class="selectedHours === range.hours
            ? 'bg-(--accent-glow) text-(--accent)'
            : 'text-(--text-3) hover:text-(--text-1)'"
        >
          {{ range.label }}
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center py-12 text-(--text-3) text-sm">
      {{ t('common.loading') }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!metricNames.length" class="text-center py-12">
      <p class="text-(--text-3) text-sm">{{ t('metrics.no_data') }}</p>
    </div>

    <!-- Metrics grid -->
    <div v-else class="space-y-8">
      <div
        v-for="name in metricNames"
        :key="name"
        class="card"
      >
        <!-- Metric header + summary stats -->
        <div class="flex items-start justify-between gap-4 mb-4 flex-wrap">
          <div>
            <span class="text-sm font-mono font-semibold text-(--text-1)">{{ name }}</span>
            <span v-if="unitFor(name)" class="text-xs text-(--text-3) ml-2">({{ unitFor(name) }})</span>
          </div>

          <!-- Summary cards -->
          <div v-if="summaryFor(name)" class="flex items-center gap-3 flex-wrap">
            <div class="text-center px-3 py-1.5 bg-(--accent-glow) rounded-lg border border-(--accent-border)">
              <p class="text-[10px] text-(--text-3) uppercase tracking-wider">{{ t('metrics.current') }}</p>
              <p class="text-sm font-bold font-display text-(--accent)">
                {{ fmtVal(summaryFor(name).last_value, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-(--bg-surface-2) rounded-lg border border-(--border)">
              <p class="text-[10px] text-(--text-3) uppercase tracking-wider">{{ t('metrics.min') }}</p>
              <p class="text-sm font-bold font-display text-(--text-2)">
                {{ fmtVal(summaryFor(name).min, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-(--bg-surface-2) rounded-lg border border-(--border)">
              <p class="text-[10px] text-(--text-3) uppercase tracking-wider">{{ t('metrics.max') }}</p>
              <p class="text-sm font-bold font-display text-(--text-2)">
                {{ fmtVal(summaryFor(name).max, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-(--bg-surface-2) rounded-lg border border-(--border)">
              <p class="text-[10px] text-(--text-3) uppercase tracking-wider">{{ t('metrics.avg') }}</p>
              <p class="text-sm font-bold font-display text-(--text-2)">
                {{ fmtVal(summaryFor(name).avg, unitFor(name)) }}
              </p>
            </div>
          </div>
        </div>

        <!-- Line chart -->
        <component
          :is="ApexChart"
          v-if="ApexChart && seriesFor(name)[0]?.data?.length"
          type="line"
          height="180"
          :options="optionsFor(name)"
          :series="seriesFor(name)"
        />
        <p v-else-if="!ApexChart" class="text-xs text-(--text-3) text-center py-6">{{ t('sweep.loading_chart') }}</p>
        <p v-else class="text-xs text-(--text-3) text-center py-6">{{ t('sweep.no_data_points') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, defineAsyncComponent, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { metricsApi } from '../../api/metrics.js'
import { cssVar } from '../../lib/themeColors.js'

const ApexChart = defineAsyncComponent(() => import('vue3-apexcharts'))

const props = defineProps({
  monitorId: {
    type: String,
    required: true,
  },
})

const { t } = useI18n()

const TIME_RANGES = [
  { hours: 1,   label: '1h' },
  { hours: 6,   label: '6h' },
  { hours: 24,  label: '24h' },
  { hours: 168, label: '7d' },
]

const selectedHours = ref(24)
const loading = ref(false)
const metrics = ref([])    // raw list
const summary = ref([])    // summary per metric_name

const metricNames = computed(() => [...new Set(metrics.value.map(m => m.metric_name))])

function unitFor(name) {
  return metrics.value.find(m => m.metric_name === name)?.unit ?? null
}

function summaryFor(name) {
  return summary.value.find(s => s.metric_name === name) ?? null
}

function seriesFor(name) {
  const pts = metrics.value
    .filter(m => m.metric_name === name)
    .map(m => ({ x: new Date(m.pushed_at).getTime(), y: m.value }))
    .sort((a, b) => a.x - b.x)
  return [{ name, data: pts }]
}

function optionsFor(name) {
  const unit = unitFor(name)
  // Couleurs design system lues à la construction des options (appelée au
  // rendu) — pas de réactivité au toggle thème exigée, re-render à la
  // navigation. Fallbacks hex pour jsdom (cssVar → '').
  const labelColor = cssVar('--text-3') || '#9a8e76'
  return {
    chart: {
      type: 'line',
      toolbar: { show: false },
      background: 'transparent',
      animations: { enabled: false },
    },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 2 },
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: labelColor }, datetimeUTC: false },
    },
    yaxis: {
      labels: {
        style: { colors: labelColor },
        formatter: v => unit ? `${fmtNum(v)} ${unit}` : fmtNum(v),
      },
    },
    grid: { borderColor: cssVar('--border') || '#322a1c' },
    theme: { mode: 'dark' },
    tooltip: {
      x: { format: 'dd/MM HH:mm:ss' },
      y: { formatter: v => unit ? `${fmtNum(v)} ${unit}` : fmtNum(v) },
    },
    legend: { show: false },
    colors: [cssVar('--accent') || '#dcab4a'],
  }
}

function fmtNum(v) {
  if (v === null || v === undefined) return '—'
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

function fmtVal(v, unit) {
  const n = fmtNum(v)
  return unit ? `${n} ${unit}` : n
}

async function load() {
  loading.value = true
  const since = new Date(Date.now() - selectedHours.value * 3600 * 1000).toISOString()
  try {
    const [metricsResp, summaryResp] = await Promise.all([
      metricsApi.list(props.monitorId, { since }),
      metricsApi.summary(props.monitorId, { since }),
    ])
    metrics.value = metricsResp.data
    summary.value = summaryResp.data
  } catch {
    metrics.value = []
    summary.value = []
  } finally {
    loading.value = false
  }
}

function setRange(hours) {
  selectedHours.value = hours
}

watch(selectedHours, load)
watch(() => props.monitorId, load)

onMounted(load)
</script>
