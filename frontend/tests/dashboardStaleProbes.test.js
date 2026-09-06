/**
 * DashboardView — "stale probe agents" section (mirrors the existing
 * "offline probes" section: same visual pattern, rows link to /probes).
 *
 * The server now computes `agent_status` on every probe ('current' /
 * 'outdated' / 'unreported') — the dashboard must surface it only when at
 * least one probe needs attention, never as a permanently-empty section.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'
import { APP_VERSION } from '../src/lib/appVersion.js'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))
vi.mock('../src/api/client', () => ({
  default: { get: apiGet, post: apiGet },
}))

import { useAuthStore } from '../src/stores/auth'
import DashboardView from '../src/views/DashboardView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const ONE_MONITOR = {
  id: 'm1',
  name: 'API',
  check_type: 'http',
  last_status: 'up',
  uptime_24h: 99.9,
  has_open_incident: false,
}

function mockApi({ probes = [] }) {
  apiGet.mockImplementation((url) => {
    if (url === '/monitors/') return Promise.resolve({ data: [ONE_MONITOR] })
    if (url === '/probes') return Promise.resolve({ data: probes })
    return Promise.resolve({ data: {} })
  })
}

async function mountDashboard() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  // Skip the onboarding-status round trip entirely — not under test here.
  auth.user = { onboarding_completed: true, is_superadmin: true }

  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: DashboardView }, { path: '/:pathMatch(.*)*', component: { template: '<div/>' } }],
  })
  router.push('/')
  await router.isReady()

  const w = mount(DashboardView, {
    global: {
      plugins: [i18n, pinia, router],
      stubs: { OnboardingWizard: true, ProbeMap: true },
    },
  })
  await flushPromises()
  await flushPromises()
  return w
}

function staleSection(w) {
  return w.findAll('.dash__section').find((s) => s.text().includes(en.dashboard.stale_probes))
}

describe('DashboardView — stale probe agents section', () => {
  beforeEach(() => {
    apiGet.mockReset()
  })

  it('does not render the section when every probe is current', async () => {
    mockApi({
      probes: [
        { id: 'p1', name: 'Paris', is_active: true, agent_status: 'current', version: APP_VERSION },
      ],
    })
    const w = await mountDashboard()
    expect(staleSection(w)).toBeUndefined()
  })

  it('lists outdated probes with an "agent vX, server on Y" message', async () => {
    mockApi({
      probes: [
        { id: 'p1', name: 'Old Agent Probe', is_active: true, last_seen_at: new Date().toISOString(), agent_status: 'outdated', version: '1.24.0' },
      ],
    })
    const w = await mountDashboard()
    const section = staleSection(w)
    expect(section).toBeDefined()
    expect(section.text()).toContain('Old Agent Probe')
    expect(section.text()).toContain(`agent v1.24.0, server on ${APP_VERSION}`)
  })

  it('lists probes with no reported version as needing attention, distinctly worded', async () => {
    mockApi({
      probes: [
        { id: 'p1', name: 'Silent Probe', is_active: true, last_seen_at: new Date().toISOString(), agent_status: 'unreported', version: null },
      ],
    })
    const w = await mountDashboard()
    const section = staleSection(w)
    expect(section).toBeDefined()
    expect(section.text()).toContain('Silent Probe')
    expect(section.text()).toContain('version not reported')
  })

  it('ignores inactive probes even if their agent is outdated', async () => {
    mockApi({
      probes: [
        { id: 'p1', name: 'Disabled Probe', is_active: false, last_seen_at: new Date().toISOString(), agent_status: 'outdated', version: '1.0.0' },
      ],
    })
    const w = await mountDashboard()
    expect(staleSection(w)).toBeUndefined()
  })

  it('ignores a probe that has never connected — it is "not started", not stale', async () => {
    mockApi({
      probes: [
        { id: 'p1', name: 'Brand New Probe', is_active: true, last_seen_at: null, agent_status: 'unreported', version: null },
      ],
    })
    const w = await mountDashboard()
    expect(staleSection(w)).toBeUndefined()
  })
})
