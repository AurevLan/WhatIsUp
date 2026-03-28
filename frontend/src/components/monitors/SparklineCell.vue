<template>
  <div class="sparkline" v-if="data.length > 1">
    <apexchart type="area" :height="28" :width="100" :options="opts" :series="series" />
  </div>
  <span v-else class="text-gray-700 text-xs">&mdash;</span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] }
})

const series = computed(() => [{ data: props.data }])

const opts = {
  chart: {
    type: 'area',
    sparkline: { enabled: true },
    animations: { enabled: false },
  },
  stroke: { curve: 'smooth', width: 1.5 },
  fill: {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.05 },
  },
  colors: ['#4f9cf9'],
  tooltip: {
    enabled: true,
    fixed: { enabled: false },
    y: { formatter: (v) => v + ' ms' },
    theme: 'dark',
  },
  yaxis: { show: false, min: 0 },
  xaxis: { type: 'numeric' },
}
</script>

<style scoped>
.sparkline { display: inline-block; vertical-align: middle; }
</style>
