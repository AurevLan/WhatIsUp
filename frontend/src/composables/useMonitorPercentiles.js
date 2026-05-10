// P50/P95/P99 response-time series for the percentiles chart.
// `chartWindowRef` is a ref holding the selected window (in hours) — same one
// fed to the availability + RT charts so all three react together.

import { computed, ref } from 'vue'
import { monitorsApi } from '../api/monitors'

export function useMonitorPercentiles(monitorIdRef, chartWindowRef) {
  const data = ref([])

  async function load() {
    try {
      const { data: rows } = await monitorsApi.percentiles(monitorIdRef.value, {
        hours: chartWindowRef.value,
      })
      data.value = rows
    } catch {
      // Silent: chart simply renders empty.
    }
  }

  const series = computed(() => [
    { name: 'P50', data: data.value.map((d) => [new Date(d.timestamp).getTime(), d.p50]) },
    { name: 'P95', data: data.value.map((d) => [new Date(d.timestamp).getTime(), d.p95]) },
    { name: 'P99', data: data.value.map((d) => [new Date(d.timestamp).getTime(), d.p99]) },
  ])

  const options = computed(() => ({
    chart: {
      type: 'line',
      height: 250,
      background: 'transparent',
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
    },
    colors: ['#34d399', '#fbbf24', '#f87171'],
    stroke: { curve: 'smooth', width: 2 },
    dataLabels: { enabled: false },
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: '#6b7280' }, datetimeUTC: false },
    },
    yaxis: {
      labels: {
        formatter: (v) => (v ? Math.round(v) + 'ms' : ''),
        style: { colors: '#6b7280' },
      },
    },
    legend: { position: 'top', labels: { colors: '#8899aa' } },
    tooltip: {
      theme: 'dark',
      x: { format: 'dd/MM HH:mm' },
      y: { formatter: (v) => (v ? v.toFixed(1) + ' ms' : '—') },
    },
    grid: { borderColor: '#1e293b' },
    theme: { mode: 'dark' },
  }))

  return { data, load, series, options }
}
