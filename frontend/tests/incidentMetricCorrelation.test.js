/**
 * Metric correlation panel (plan V2, C-3).
 *
 * The panel presents a ranked table, which is a shape that invites the reader to
 * infer a cause. Most of what is pinned here is that it does not let them: every
 * "not comparable" reason is rendered as words rather than silently becoming a
 * number, and the disclaimer is always present.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/incidentUpdates', () => ({
  incidentUpdatesApi: { metricCorrelation: vi.fn() },
}))

import { incidentUpdatesApi } from '../src/api/incidentUpdates'
import IncidentMetricCorrelationPanel from '../src/components/incidents/IncidentMetricCorrelationPanel.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

function series(overrides = {}) {
  return {
    metric_name: 'queue_depth',
    labels: {},
    unit: null,
    incident_avg: 40,
    incident_samples: 10,
    baseline_avg: 10,
    baseline_samples: 10,
    change_ratio: 3,
    change_absolute: 30,
    not_comparable: null,
    ...overrides,
  }
}

async function render(payload) {
  incidentUpdatesApi.metricCorrelation.mockResolvedValue({
    data: {
      incident_id: 'inc-1',
      window_start: '2026-08-09T11:00:00Z',
      window_end: '2026-08-09T12:00:00Z',
      baseline_start: '2026-08-09T10:00:00Z',
      window_seconds: 3600,
      series: [],
      ...payload,
    },
  })
  const w = mount(IncidentMetricCorrelationPanel, {
    props: { incidentId: 'inc-1' },
    global: { plugins: [i18n] },
  })
  await flushPromises()
  return w
}

describe('IncidentMetricCorrelationPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders a measured change as a signed percentage', async () => {
    const w = await render({ series: [series()] })
    expect(w.text()).toContain('queue_depth')
    expect(w.text()).toContain('+300%')
  })

  it('renders labels alongside the name, in stable order', async () => {
    const w = await render({
      series: [series({ labels: { route: '/api', method: 'GET' } })],
    })
    expect(w.text()).toContain('queue_depth{method="GET",route="/api"}')
  })

  it.each([
    ['no_baseline', en.correlation.reason_no_baseline],
    ['too_few_samples', en.correlation.reason_too_few_samples],
    ['no_incident_data', en.correlation.reason_no_incident_data],
  ])('says why %s cannot be compared instead of showing a number', async (reason, label) => {
    const w = await render({
      series: [series({ change_ratio: null, change_absolute: null, not_comparable: reason })],
    })
    expect(w.text()).toContain(label)
    expect(w.text()).not.toContain('%')
  })

  it('falls back to an absolute delta when the baseline was zero', async () => {
    const w = await render({
      series: [
        series({
          baseline_avg: 0,
          incident_avg: 7,
          change_ratio: null,
          change_absolute: 7,
          not_comparable: 'zero_baseline',
          unit: 'errors',
        }),
      ],
    })
    // A ratio against zero would be infinite; the delta is the honest form.
    expect(w.text()).toContain('+7 errors')
  })

  it('always states that this is correlation, not causation', async () => {
    const w = await render({ series: [series()] })
    expect(w.text()).toContain(en.correlation.disclaimer)
  })

  it('says plainly when the monitor pushes no metrics', async () => {
    const w = await render({ series: [] })
    expect(w.text()).toContain(en.correlation.no_metrics)
    // No table at all, rather than an empty one that reads as "nothing moved".
    expect(w.find('table').exists()).toBe(false)
  })

  it('surfaces an API failure instead of rendering an empty result', async () => {
    incidentUpdatesApi.metricCorrelation.mockRejectedValue({
      response: { data: { detail: 'boom' } },
    })
    const w = mount(IncidentMetricCorrelationPanel, {
      props: { incidentId: 'inc-1' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    expect(w.text()).toContain('boom')
    expect(w.text()).not.toContain(en.correlation.no_metrics)
  })
})
