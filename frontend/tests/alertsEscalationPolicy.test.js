/**
 * Escalation policy selector in AlertsView (chantier ergonomie, item 1).
 *
 * AlertRule.escalation_policy_id has driven the escalation engine (plan V2,
 * B-1/B-2) since it shipped, but nothing in the frontend let an operator
 * attach a policy to a rule — the only way in was calling the API by hand.
 * These tests pin the value actually reaching the server on both create and
 * PATCH, including explicitly clearing it back to "None".
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
vi.mock('../src/api/oncall', () => ({
  oncallApi: { policies: { list: vi.fn() } },
}))
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isSuperadmin: false }) }))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

import api from '../src/api/client'
import { monitorsApi, groupsApi } from '../src/api/monitors'
import { metricsApi } from '../src/api/metrics'
import { oncallApi } from '../src/api/oncall'
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

const POLICIES = [
  { id: 'pol-1', name: 'Primary on-call' },
  { id: 'pol-2', name: 'Weekend escalation' },
]

async function mountView() {
  api.get.mockImplementation((url) => {
    if (url === '/alerts/channels') return Promise.resolve({ data: [{ id: 'ch-1', name: 'Ops', type: 'slack' }] })
    if (url === '/alerts/rules') return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [] })
  })
  monitorsApi.list.mockResolvedValue({ data: [{ id: 'mon-1', name: 'API', check_type: 'http' }] })
  groupsApi.list.mockResolvedValue({ data: [{ id: 'grp-1', name: 'Prod' }] })
  metricsApi.summary.mockResolvedValue({ data: [] })
  metricsApi.series.mockResolvedValue({ data: [] })
  oncallApi.policies.list.mockResolvedValue({ data: POLICIES })

  const wrapper = mount(AlertsView, { global: { plugins: [i18n], stubs: globalStubs } })
  await flushPromises()
  return wrapper
}

describe('AlertsView — escalation policy selector', () => {
  beforeEach(() => vi.clearAllMocks())

  it('fetches the policy list and offers it plus an explicit "none"', async () => {
    const w = await mountView()
    w.vm.openCreateRule()
    await flushPromises()

    expect(oncallApi.policies.list).toHaveBeenCalled()
    expect(w.text()).toContain(en.alerts.escalation_policy_label)
    expect(w.text()).toContain('Primary on-call')
    expect(w.text()).toContain('Weekend escalation')
    expect(w.text()).toContain(en.alerts.escalation_policy_none)
  })

  it('sends the selected policy id when creating a rule', async () => {
    const w = await mountView()
    api.post.mockResolvedValue({ data: {} })
    w.vm.openCreateRule()
    Object.assign(w.vm.ruleForm, {
      target_type: 'monitor',
      target_id: 'mon-1',
      condition: 'any_down',
      channel_ids: ['ch-1'],
      escalation_policy_id: 'pol-1',
    })
    await w.vm.saveRule()

    const [, payload] = api.post.mock.calls.find(([url]) => url === '/alerts/rules')
    expect(payload.escalation_policy_id).toBe('pol-1')
  })

  it('omits escalation_policy_id on create when left at "none"', async () => {
    const w = await mountView()
    api.post.mockResolvedValue({ data: {} })
    w.vm.openCreateRule()
    Object.assign(w.vm.ruleForm, {
      target_type: 'monitor',
      target_id: 'mon-1',
      condition: 'any_down',
      channel_ids: ['ch-1'],
    })
    await w.vm.saveRule()

    const [, payload] = api.post.mock.calls.find(([url]) => url === '/alerts/rules')
    expect(payload.escalation_policy_id).toBeUndefined()
  })

  it('preloads the current policy when editing, and sends null when cleared', async () => {
    const w = await mountView()
    api.patch.mockResolvedValue({ data: {} })
    const rule = {
      id: 'rule-1',
      monitor_id: 'mon-1',
      condition: 'any_down',
      channels: [{ id: 'ch-1' }],
      escalation_policy_id: 'pol-2',
    }
    w.vm.openEditRule(rule)
    await flushPromises()
    expect(w.vm.ruleForm.escalation_policy_id).toBe('pol-2')

    // Detaching: the PATCH must carry the explicit null, not omit the field —
    // otherwise a rule can never be un-escalated from this form.
    w.vm.ruleForm.escalation_policy_id = null
    await w.vm.saveRule()

    const [, payload] = api.patch.mock.calls.find(([url]) => url === '/alerts/rules/rule-1')
    expect(payload.escalation_policy_id).toBeNull()
  })
})
