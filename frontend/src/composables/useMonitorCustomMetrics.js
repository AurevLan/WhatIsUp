// Custom metrics dashboard for MonitorDetailView. The push URL modal lives in
// the parent template; this composable owns the data + chart series/options.
//
// Since C-1 a metric *name* can carry several *series*, told apart by their
// labels (`http_latency{route="/api"}`). One chart per name, one line per
// series inside it — drawing a line per name would average dimensions together
// and report a number that describes nothing in particular.

import { computed, ref } from 'vue'
import { metricsApi } from '../api/metrics'

/** `{route="/api",method="GET"}` — stable order, so the legend never reshuffles. */
export function formatLabels(labels) {
  const entries = Object.entries(labels || {}).sort(([a], [b]) => a.localeCompare(b))
  if (!entries.length) return ''
  return `{${entries.map(([k, v]) => `${k}="${v}"`).join(',')}}`
}

/** Identity of a series within a name, mirroring the server's series_hash inputs. */
function seriesKey(point) {
  return formatLabels(point.labels)
}

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

  /** Distinct label sets seen for a name, as display strings. */
  function labelSets(name) {
    return [
      ...new Set(metrics.value.filter((m) => m.metric_name === name).map(seriesKey)),
    ].sort()
  }

  function series(name) {
    const points = metrics.value.filter((m) => m.metric_name === name)
    const keys = [...new Set(points.map(seriesKey))].sort()
    return keys.map((key) => ({
      // A label-less series keeps the bare metric name, so single-series
      // metrics look exactly as they did before C-1.
      name: key ? `${name}${key}` : name,
      data: points
        .filter((m) => seriesKey(m) === key)
        .map((m) => ({ x: new Date(m.pushed_at).getTime(), y: m.value }))
        .sort((a, b) => a.x - b.x),
    }))
  }

  function options(name) {
    const u = unit(name)
    const multi = labelSets(name).length > 1
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
      // Only worth the vertical space once there is more than one line.
      legend: { show: multi, position: 'bottom', labels: { colors: '#6b7280' } },
    }
  }

  return {
    metrics,
    showPushUrlModal,
    names,
    unit,
    labelSets,
    series,
    options,
    load,
  }
}
