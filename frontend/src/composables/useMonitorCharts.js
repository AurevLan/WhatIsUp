// ApexCharts series + options for the Availability tab — response-time per
// probe (line) and aggregated availability (bar). Both reactive on the shared
// `chartWindow` ref so the timezone selector wakes both charts at once.
//
// The RT options pull cross-tab state: `annotations` for vertical markers and
// `incidents` for translucent red bands. Owners must keep those refs in scope
// at the parent level (don't mount them inside a tab that may unmount).

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { cssVar } from '../lib/themeColors'

// Palette multi-séries VELOURS — hex fixes assumés (il faut N teintes
// distinctes, pas une seule variable de thème) mais choisis chauds et lisibles
// sur les deux thèmes : or, sauge, terracotta, brun, olive, vieux rose,
// cuivre, taupe.
export const PROBE_COLORS = [
  '#d9a440', // or
  '#85a883', // sauge
  '#c96b4b', // terracotta
  '#8c6a52', // brun
  '#a4a04e', // olive
  '#c08497', // vieux rose
  '#b5713a', // cuivre
  '#9c8f7f', // taupe
]

function chartBucketMin(h) {
  if (h <= 6) return 15
  if (h <= 24) return 30
  if (h <= 72) return 120
  return 240
}

export function useMonitorCharts({
  results,
  incidents,
  annotations,
  alertRules,
  chartWindow,
  probeName,
}) {
  const { t } = useI18n()

  const rtThresholdMs = computed(() => {
    const rule = alertRules.value.find(
      (r) => r.condition === 'response_time_above' && r.threshold_value != null,
    )
    return rule?.threshold_value ?? null
  })

  const rtSeries = computed(() => {
    if (!results.value.length) return []
    const byProbe = {}
    for (const r of results.value) {
      if (r.response_time_ms === null) continue
      if (!byProbe[r.probe_id]) byProbe[r.probe_id] = []
      byProbe[r.probe_id].push({
        x: new Date(r.checked_at).getTime(),
        y: Math.round(r.response_time_ms),
      })
    }
    return Object.entries(byProbe).map(([pid, data], i) => ({
      name: probeName(pid),
      data: data.sort((a, b) => a.x - b.x),
      color: PROBE_COLORS[i % PROBE_COLORS.length],
    }))
  })

  // Couleurs design system lues à l'évaluation des computeds (re-render à la
  // navigation / au refetch — pas de réactivité au toggle thème exigée).
  // Fallbacks hex pour jsdom (cssVar → '').
  const rtOptions = computed(() => {
    const labelColor = cssVar('--text-3') || '#9a8e76'
    const gridColor = cssVar('--border') || '#322a1c'
    const accent = cssVar('--accent') || '#dcab4a'
    const down = cssVar('--down') || '#e8876b'
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
      yaxis: { labels: { style: { colors: labelColor }, formatter: (v) => v + 'ms' } },
      legend: { show: false },
      grid: { borderColor: gridColor },
      theme: { mode: 'dark' },
      tooltip: { x: { format: 'dd/MM HH:mm:ss' }, y: { formatter: (v) => v + ' ms' } },
      annotations: {
        xaxis: [
          ...annotations.value.map((a) => ({
            x: new Date(a.annotated_at).getTime(),
            strokeDashArray: 4,
            borderColor: accent,
            label: {
              text: a.content.length > 25 ? a.content.slice(0, 25) + '…' : a.content,
              style: {
                color: '#fff',
                background: accent,
                fontSize: '10px',
                padding: { left: 6, right: 6, top: 2, bottom: 2 },
              },
              position: 'top',
              orientation: 'vertical',
            },
          })),
          ...incidents.value.map((inc) => ({
            x: new Date(inc.started_at).getTime(),
            x2: inc.resolved_at ? new Date(inc.resolved_at).getTime() : Date.now(),
            fillColor: down,
            opacity: 0.08,
            label: {
              text: '⚠ Incident',
              style: { color: down, background: 'transparent', fontSize: '10px' },
              orientation: 'horizontal',
              position: 'front',
            },
          })),
        ],
        yaxis:
          rtThresholdMs.value != null
            ? [
                {
                  y: rtThresholdMs.value,
                  borderColor: down,
                  strokeDashArray: 4,
                  label: {
                    text: `Alert: ${rtThresholdMs.value}ms`,
                    style: {
                      color: '#fff',
                      background: down,
                      fontSize: '10px',
                      padding: { left: 6, right: 6, top: 2, bottom: 2 },
                    },
                    position: 'right',
                  },
                },
              ]
            : [],
      },
    }
  })

  const availSeries = computed(() => {
    if (!results.value.length) return [{ name: 'Availability', data: [] }]

    const now = Date.now()
    const window = chartWindow.value * 60 * 60 * 1000
    const bucket = chartBucketMin(chartWindow.value) * 60 * 1000
    const count = Math.floor(window / bucket)

    const buckets = Array.from({ length: count }, (_, i) => ({
      ts: now - window + (i + 1) * bucket,
      total: 0,
      up: 0,
    }))

    for (const r of results.value) {
      const ts = new Date(r.checked_at).getTime()
      const idx = Math.floor((ts - (now - window)) / bucket)
      if (idx >= 0 && idx < count) {
        buckets[idx].total++
        if (r.status === 'up') buckets[idx].up++
      }
    }

    return [
      {
        name: 'Availability',
        data: buckets.map((b) => ({
          x: b.ts,
          y: b.total > 0 ? Math.round((b.up / b.total) * 100) : null,
        })),
      },
    ]
  })

  const availOptions = computed(() => {
    const labelColor = cssVar('--text-3') || '#9a8e76'
    return {
      chart: {
        type: 'bar',
        toolbar: { show: false },
        background: 'transparent',
        animations: { enabled: false },
      },
      plotOptions: {
        bar: {
          columnWidth: '90%',
          colors: {
            ranges: [
              { from: 0, to: 49, color: cssVar('--down') || '#e8876b' },
              { from: 50, to: 99, color: cssVar('--warn') || '#dcab4a' },
              { from: 99, to: 100, color: cssVar('--up') || '#8fc09e' },
            ],
          },
        },
      },
      dataLabels: { enabled: false },
      xaxis: {
        type: 'datetime',
        labels: { style: { colors: labelColor }, datetimeUTC: false, format: 'HH:mm' },
      },
      yaxis: {
        min: 0,
        max: 100,
        tickAmount: 4,
        labels: { style: { colors: labelColor }, formatter: (v) => v + '%' },
      },
      grid: { borderColor: cssVar('--border') || '#322a1c' },
      theme: { mode: 'dark' },
      tooltip: {
        x: { format: 'dd/MM HH:mm' },
        y: { formatter: (v) => (v !== null ? v + '% probes UP' : t('monitor_detail.no_data')) },
      },
    }
  })

  return {
    rtThresholdMs,
    rtSeries,
    rtOptions,
    availSeries,
    availOptions,
    chartBucketMin,
    PROBE_COLORS,
  }
}
