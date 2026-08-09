/**
 * Charting labelled metric series (plan V2, C-1).
 *
 * Since labels exist, a metric *name* can carry several *series*. Drawing one
 * line per name would average dimensions together and plot a number that
 * describes nothing in particular — so the grouping is what this pins down,
 * along with the property that a label-less metric still looks exactly as it
 * did before C-1.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('../src/api/metrics', () => ({
  metricsApi: { list: vi.fn(), summary: vi.fn(), series: vi.fn() },
}))

import { metricsApi } from '../src/api/metrics'
import { useMonitorCustomMetrics, formatLabels } from '../src/composables/useMonitorCustomMetrics'

const monitor = ref({ id: 'mon-1' })

function point(name, value, labels, pushed_at, unit = null) {
  return { metric_name: name, value, labels, pushed_at, unit }
}

describe('formatLabels', () => {
  it('is stable regardless of key order, so the legend never reshuffles', () => {
    expect(formatLabels({ b: '2', a: '1' })).toBe('{a="1",b="2"}')
    expect(formatLabels({ a: '1', b: '2' })).toBe(formatLabels({ b: '2', a: '1' }))
  })

  it('renders a label-less series as the empty string', () => {
    expect(formatLabels({})).toBe('')
    expect(formatLabels(null)).toBe('')
  })
})

describe('useMonitorCustomMetrics — grouping by series', () => {
  beforeEach(() => vi.clearAllMocks())

  it('splits one name into one line per label set', async () => {
    metricsApi.list.mockResolvedValue({
      data: [
        point('http_latency', 42, { route: '/api' }, '2026-08-09T10:00:00Z'),
        point('http_latency', 43, { route: '/api' }, '2026-08-09T10:01:00Z'),
        point('http_latency', 12, { route: '/health' }, '2026-08-09T10:00:00Z'),
      ],
    })
    const state = useMonitorCustomMetrics(monitor)
    await state.load()

    expect(state.names.value).toEqual(['http_latency'])
    const series = state.series('http_latency')
    expect(series.map((s) => s.name)).toEqual([
      'http_latency{route="/api"}',
      'http_latency{route="/health"}',
    ])
    expect(series[0].data).toHaveLength(2)
    expect(series[1].data).toHaveLength(1)
  })

  it('leaves a label-less metric looking exactly as before C-1', async () => {
    metricsApi.list.mockResolvedValue({
      data: [
        point('orders', 1, {}, '2026-08-09T10:00:00Z', 'req/min'),
        point('orders', 2, null, '2026-08-09T10:01:00Z', 'req/min'),
      ],
    })
    const state = useMonitorCustomMetrics(monitor)
    await state.load()

    const series = state.series('orders')
    expect(series).toHaveLength(1)
    // The bare name, not `orders{}`.
    expect(series[0].name).toBe('orders')
    // A single line needs no legend.
    expect(state.options('orders').legend.show).toBe(false)
  })

  it('shows the legend once a name carries more than one series', async () => {
    metricsApi.list.mockResolvedValue({
      data: [
        point('http_latency', 1, { route: '/a' }, '2026-08-09T10:00:00Z'),
        point('http_latency', 2, { route: '/b' }, '2026-08-09T10:00:00Z'),
      ],
    })
    const state = useMonitorCustomMetrics(monitor)
    await state.load()

    expect(state.labelSets('http_latency')).toHaveLength(2)
    expect(state.options('http_latency').legend.show).toBe(true)
  })

  it('orders points chronologically within each series', async () => {
    metricsApi.list.mockResolvedValue({
      data: [
        point('q', 3, {}, '2026-08-09T10:02:00Z'),
        point('q', 1, {}, '2026-08-09T10:00:00Z'),
        point('q', 2, {}, '2026-08-09T10:01:00Z'),
      ],
    })
    const state = useMonitorCustomMetrics(monitor)
    await state.load()
    expect(state.series('q')[0].data.map((d) => d.y)).toEqual([1, 2, 3])
  })

  it('degrades to an empty chart when the API fails', async () => {
    metricsApi.list.mockRejectedValue(new Error('boom'))
    const state = useMonitorCustomMetrics(monitor)
    await state.load()
    expect(state.metrics.value).toEqual([])
    expect(state.names.value).toEqual([])
  })
})
