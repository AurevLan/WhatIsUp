<template>
  <div>
    <!-- Header: title + time range selector -->
    <div class="flex items-center justify-between mb-6 flex-wrap gap-3">
      <h2 class="text-sm font-semibold text-gray-300">{{ t('metrics.title') }}</h2>
      <div class="inline-flex rounded-md border border-gray-800 overflow-hidden">
        <button
          v-for="range in TIME_RANGES"
          :key="range.hours"
          @click="setRange(range.hours)"
          class="px-3 py-1.5 text-xs font-medium transition-colors border-r border-gray-800 last:border-r-0"
          :class="selectedHours === range.hours
            ? 'bg-blue-600/30 text-blue-300'
            : 'text-gray-500 hover:text-gray-300'"
        >
          {{ range.label }}
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center py-12 text-gray-500 text-sm">
      {{ t('common.loading') }}
    </div>

    <!-- Empty state -->
    <div v-else-if="!metricNames.length" class="text-center py-12">
      <p class="text-gray-500 text-sm">{{ t('metrics.no_data') }}</p>
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
            <span class="text-sm font-mono font-semibold text-gray-200">{{ name }}</span>
            <span v-if="unitFor(name)" class="text-xs text-gray-500 ml-2">({{ unitFor(name) }})</span>
          </div>

          <!-- Summary cards -->
          <div v-if="summaryFor(name)" class="flex items-center gap-3 flex-wrap">
            <div class="text-center px-3 py-1.5 bg-blue-950/40 rounded-lg border border-blue-900/40">
              <p class="text-[10px] text-gray-500 uppercase tracking-wider">{{ t('metrics.current') }}</p>
              <p class="text-sm font-bold text-blue-300">
                {{ fmtVal(summaryFor(name).last_value, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-gray-800/50 rounded-lg border border-gray-700/40">
              <p class="text-[10px] text-gray-500 uppercase tracking-wider">{{ t('metrics.min') }}</p>
              <p class="text-sm font-bold text-gray-300">
                {{ fmtVal(summaryFor(name).min, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-gray-800/50 rounded-lg border border-gray-700/40">
              <p class="text-[10px] text-gray-500 uppercase tracking-wider">{{ t('metrics.max') }}</p>
              <p class="text-sm font-bold text-gray-300">
                {{ fmtVal(summaryFor(name).max, unitFor(name)) }}
              </p>
            </div>
            <div class="text-center px-3 py-1.5 bg-gray-800/50 rounded-lg border border-gray-700/40">
              <p class="text-[10px] text-gray-500 uppercase tracking-wider">{{ t('metrics.avg') }}</p>
              <p class="text-sm font-bold text-gray-300">
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
        <p v-else-if="!ApexChart" class="text-xs text-gray-600 text-center py-6">Loading chart…</p>
        <p v-else class="text-xs text-gray-600 text-center py-6">No data points in this range.</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, defineAsyncComponent, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { metricsApi } from '../../api/metrics.js'

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
      labels: { style: { colors: '#6b7280' }, datetimeUTC: false },
    },
    yaxis: {
      labels: {
        style: { colors: '#6b7280' },
        formatter: v => unit ? `${fmtNum(v)} ${unit}` : fmtNum(v),
      },
    },
    grid: { borderColor: '#1e293b' },
    theme: { mode: 'dark' },
    tooltip: {
      x: { format: 'dd/MM HH:mm:ss' },
      y: { formatter: v => unit ? `${fmtNum(v)} ${unit}` : fmtNum(v) },
    },
    legend: { show: false },
    colors: ['#3b82f6'],
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
