/**
 * §1.2, plan cap v2 6c — Astreinte (on-call) declassed from a top-level nav
 * entry to a tab inside AlertsView. Nothing is removed: /oncall still
 * resolves to the same OnCallView, and this tab renders the exact same
 * component — just reachable from Alertes, where it belongs as alert
 * configuration rather than a first-level destination.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
vi.mock('../src/api/monitors', () => ({
  monitorsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
  groupsApi: { list: vi.fn().mockResolvedValue({ data: [] }) },
}))
vi.mock('../src/api/metrics', () => ({
  metricsApi: { summary: vi.fn().mockResolvedValue({ data: [] }), series: vi.fn() },
}))
vi.mock('../src/api/oncall', () => ({
  oncallApi: {
    policies: { list: vi.fn().mockResolvedValue({ data: [] }) },
    schedules: { list: vi.fn().mockResolvedValue({ data: [] }) },
    onCallNow: vi.fn().mockResolvedValue({ data: [] }),
  },
}))
vi.mock('../src/stores/auth', () => ({ useAuthStore: () => ({ isSuperadmin: false }) }))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))
vi.mock('../src/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}))

import api from '../src/api/client'
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
  OnCallScheduleModal: true,
  EscalationPolicyModal: true,
}

function makeRouter(initialPath = '/alerts') {
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/alerts', component: stub }, { path: '/:pathMatch(.*)*', component: stub }],
  })
  router.push(initialPath)
  return router
}

async function mountView(initialPath) {
  api.get.mockImplementation((url) => {
    if (url === '/alerts/channels') return Promise.resolve({ data: [] })
    if (url === '/alerts/rules') return Promise.resolve({ data: [] })
    return Promise.resolve({ data: [] })
  })
  const router = makeRouter(initialPath)
  await router.isReady()
  const w = mount(AlertsView, { global: { plugins: [i18n, router], stubs: globalStubs } })
  await flushPromises()
  return { w, router }
}

describe('AlertsView — Astreinte tab (§1.2)', () => {
  it('defaults to the Rules tab', async () => {
    const { w } = await mountView()
    expect(w.text()).toContain(en.alerts.channels)
    expect(w.text()).not.toContain(en.oncall.subtitle)
  })

  it('switches to the On-call tab and renders OnCallView', async () => {
    const { w } = await mountView()
    const tab = w.findAll('button').find((b) => b.text() === en.alerts.tab_oncall)
    expect(tab).toBeTruthy()
    await tab.trigger('click')
    await flushPromises()
    expect(w.text()).toContain(en.oncall.subtitle)
  })

  it('opens directly on the On-call tab via ?tab=oncall (command palette / bookmarks)', async () => {
    const { w } = await mountView('/alerts?tab=oncall')
    expect(w.text()).toContain(en.oncall.subtitle)
  })
})
