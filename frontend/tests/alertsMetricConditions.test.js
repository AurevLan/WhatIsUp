/**
 * Pushed-metric alert conditions in AlertsView (plan V2, C-4).
 *
 * The backend rejects a metric rule that has no monitor_id, no metric_name or
 * (for above/below) no threshold. Each of those is a 422 the operator sees only
 * after clicking save, so the form has to make them unreachable — that is what
 * this file pins down, plus the payload actually carrying the two new fields.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../src/api/monitors', () => ({
  monitorsApi: { list: vi.fn(), update: vi.fn() },
  groupsApi: { list: vi.fn() },
}))
vi.mock('../src/api/metrics', () => ({
  metricsApi: { summary: vi.fn(), series: vi.fn() },
}))
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isSuperadmin: false }) }))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

import api from '../src/api/client'
import { monitorsApi, groupsApi } from '../src/api/monitors'
import { metricsApi } from '../src/api/metrics'
import AlertsView from '../src/views/AlertsView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const globalStubs = {
  AddChannelModal: true,
  AlertTemplatesSection: true,
  EmptyState: true,
  BaseModal: {
    props: ['modelValue', 'title', 'size'],
    template: '<div v-if="modelValue" class="modal-stub"><slot /></div>',
  },
}

async function mountView() {
  api.get.mockImplementation((url) => {
    if (url === '/alerts/channels') return Promise.resolve({ data: [{ id: 'ch-1', name: 'Ops', type: 'slack' }] })
    if (url === '/alerts/rules') return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [] })
  })
  monitorsApi.list.mockResolvedValue({ data: [{ id: 'mon-1', name: 'API', check_type: 'http' }] })
  groupsApi.list.mockResolvedValue({ data: [{ id: 'grp-1', name: 'Prod' }] })
  metricsApi.summary.mockResolvedValue({ data: [] })
  // The rule form reads the series registry, not the points: a series that has
  // gone quiet must still be pickable for a `metric_absent` rule.
  metricsApi.series.mockResolvedValue({
    data: [
      { metric_name: 'queue_depth', labels: {} },
      { metric_name: 'http_latency', labels: { route: '/api', method: 'GET' } },
      { metric_name: 'http_latency', labels: { route: '/health', method: 'GET' } },
    ],
  })

  const wrapper = mount(AlertsView, { global: { plugins: [i18n], stubs: globalStubs } })
  await flushPromises()
  return wrapper
}

describe('AlertsView — pushed-metric conditions', () => {
  beforeEach(() => vi.clearAllMocks())

  it('offers the metric conditions only when the target is a monitor', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    await flushPromises()

    const options = () => w.findAll('option').map((o) => o.attributes('value'))
    expect(options()).toContain('metric_above')

    // Metrics are pushed to POST /metrics/{monitor_id}: a group-scoped rule has
    // no series to read, and the API refuses it.
    w.vm.ruleForm.target_type = 'group'
    await flushPromises()
    expect(options()).not.toContain('metric_above')
  })

  it('falls back to any_down when the target switches away from a monitor', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    w.vm.ruleForm.condition = 'metric_below'
    await flushPromises()

    w.vm.ruleForm.target_type = 'group'
    await flushPromises()
    expect(w.vm.ruleForm.condition).toBe('any_down')
  })

  it('suggests the metric names already pushed on the selected monitor', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    w.vm.ruleForm.condition = 'metric_above'
    w.vm.ruleForm.target_id = 'mon-1'
    await flushPromises()

    expect(metricsApi.series).toHaveBeenCalledWith('mon-1')
    // Distinct names, not one entry per series.
    expect(
      w.find('#metric-name-options').findAll('option').map((o) => o.attributes('value')),
    ).toEqual(['queue_depth', 'http_latency'])
  })

  it('offers a series picker only when the name covers several (C-1)', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    w.vm.ruleForm.condition = 'metric_above'
    w.vm.ruleForm.target_id = 'mon-1'
    await flushPromises()

    // A label-less metric is a single series: nothing to choose.
    w.vm.ruleForm.metric_name = 'queue_depth'
    await flushPromises()
    expect(w.text()).not.toContain(en.alerts.metric_labels_label)

    w.vm.ruleForm.metric_name = 'http_latency'
    await flushPromises()
    expect(w.text()).toContain(en.alerts.metric_labels_label)
    expect(w.findAll('option').map((o) => o.attributes('value'))).toContain(
      '{method="GET",route="/api"}',
    )
  })

  it('sends the selected series labels, and none when watching them all', async () => {
    const w = await mountView()
    api.post.mockResolvedValue({ data: {} })
    w.vm.openCreateRule()
    Object.assign(w.vm.ruleForm, {
      target_type: 'monitor',
      target_id: 'mon-1',
      condition: 'metric_above',
      threshold_value: 100,
      metric_name: 'http_latency',
      channel_ids: ['ch-1'],
    })
    await flushPromises()

    w.vm.selectedSeriesKey = '{method="GET",route="/api"}'
    await w.vm.saveRule()
    let [, payload] = api.post.mock.calls.find(([url]) => url === '/alerts/rules')
    expect(payload.metric_labels).toEqual({ route: '/api', method: 'GET' })

    // Back to "any series": the selector must be dropped rather than sent
    // empty, so the stored rule reads as "watch them all".
    api.post.mockClear()
    w.vm.selectedSeriesKey = ''
    await w.vm.saveRule()
    ;[, payload] = api.post.mock.calls.find(([url]) => url === '/alerts/rules')
    expect(payload.metric_labels).toBeUndefined()
  })

  it('sends metric_name and metric_window_seconds when creating the rule', async () => {
    const w = await mountView()
    api.post.mockResolvedValue({ data: {} })
    w.vm.openCreateRule()
    Object.assign(w.vm.ruleForm, {
      target_type: 'monitor',
      target_id: 'mon-1',
      condition: 'metric_above',
      threshold_value: 1000,
      metric_name: 'queue_depth',
      metric_window_seconds: 120,
      channel_ids: ['ch-1'],
    })
    await w.vm.saveRule()

    const [, payload] = api.post.mock.calls.find(([url]) => url === '/alerts/rules')
    expect(payload).toMatchObject({
      monitor_id: 'mon-1',
      condition: 'metric_above',
      threshold_value: 1000,
      metric_name: 'queue_depth',
      metric_window_seconds: 120,
    })
  })

  it('hides the threshold input for metric_absent, which has none', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    w.vm.ruleForm.condition = 'metric_above'
    await flushPromises()
    expect(w.text()).toContain(en.alerts.metric_threshold_label)

    w.vm.ruleForm.condition = 'metric_absent'
    await flushPromises()
    expect(w.text()).not.toContain(en.alerts.metric_threshold_label)
  })
})
