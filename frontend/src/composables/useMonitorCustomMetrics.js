// Custom metrics dashboard for MonitorDetailView. The push URL modal lives in
// the parent template; this composable owns the data + chart series/options.

import { computed, ref } from 'vue'
import { metricsApi } from '../api/metrics'

export function useMonitorCustomMetrics(monitorRef) {
  const metrics = ref([])
  const showPushUrlModal = ref(false)

  async function load() {
    if (!monitorRef.value) return
    try {
      const { data } = await metricsApi.list(monitorRef.value.id, { hours: 24 })
      metrics.value = data
    } catch {
      metrics.value = []
    }
  }

  const names = computed(() => [...new Set(metrics.value.map((m) => m.metric_name))])

  function unit(name) {
    return metrics.value.find((m) => m.metric_name === name)?.unit ?? null
  }

  function series(name) {
    const pts = metrics.value
      .filter((m) => m.metric_name === name)
      .map((m) => ({ x: new Date(m.pushed_at).getTime(), y: m.value }))
      .sort((a, b) => a.x - b.x)
    return [{ name, data: pts }]
  }

  function options(name) {
    const u = unit(name)
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
          formatter: (v) => (u ? `${v} ${u}` : String(v)),
        },
      },
      grid: { borderColor: '#1e293b' },
      theme: { mode: 'dark' },
      tooltip: {
        x: { format: 'dd/MM HH:mm:ss' },
        y: { formatter: (v) => (u ? `${v} ${u}` : String(v)) },
      },
      legend: { show: false },
    }
  }

  return {
    metrics,
    showPushUrlModal,
    names,
    unit,
    series,
    options,
    load,
  }
}
