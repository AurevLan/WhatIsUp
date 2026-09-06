/**
 * ProbesView — agent-staleness badge now reads the server-computed
 * `agent_status` field instead of comparing `probe.version` against a
 * separately-fetched `/api/health` response (removed: it served no other
 * purpose in this view).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import en from '../src/i18n/en.js'
import { APP_VERSION } from '../src/lib/appVersion.js'

const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }))
vi.mock('../src/api/client', () => ({
  default: { get: apiGet, post: apiGet, patch: apiGet, delete: apiGet },
}))

import { useAuthStore } from '../src/stores/auth'
import ProbesView from '../src/views/ProbesView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

function mockProbes(probes) {
  apiGet.mockImplementation((url) => {
    if (url === '/probes/') return Promise.resolve({ data: probes })
    return Promise.resolve({ data: [] })
  })
}

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.user = { is_superadmin: false }

  const w = mount(ProbesView, {
    global: {
      plugins: [i18n, pinia],
      stubs: { 'router-link': { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  await flushPromises()
  return w
}

describe('ProbesView — agent_status badge', () => {
  beforeEach(() => apiGet.mockReset())

  it('flags a probe that never reported a version, even though it has connected', async () => {
    mockProbes([
      { id: 'p1', name: 'Silent', location_name: 'X', is_active: true, last_seen_at: new Date().toISOString(), version: null, agent_status: 'unreported' },
    ])
    const w = await mountView()
    expect(w.text()).toContain(en.probes.version_unknown)
  })

  it('does not flag a probe that has never connected at all, even though it has no version', async () => {
    mockProbes([
      { id: 'p1', name: 'Fresh', location_name: 'X', is_active: true, last_seen_at: null, version: null, agent_status: 'unreported' },
    ])
    const w = await mountView()
    expect(w.text()).not.toContain(en.probes.version_unknown)
  })

  it('shows a plain badge for a probe at the server version', async () => {
    mockProbes([
      { id: 'p1', name: 'Current', location_name: 'X', is_active: true, last_seen_at: new Date().toISOString(), version: APP_VERSION, agent_status: 'current' },
    ])
    const w = await mountView()
    expect(w.text()).toContain(`v${APP_VERSION}`)
    expect(w.text()).not.toContain(en.probes.version_outdated)
  })

  it('flags an outdated probe without needing a separate /api/health fetch', async () => {
    mockProbes([
      { id: 'p1', name: 'Old', location_name: 'X', is_active: true, last_seen_at: new Date().toISOString(), version: '1.0.0', agent_status: 'outdated' },
    ])
    const w = await mountView()
    expect(w.text()).toContain(en.probes.version_outdated)
    // Only one network call was ever made: the probes list itself.
    const urls = apiGet.mock.calls.map((c) => c[0])
    expect(urls.every((u) => !String(u).includes('/api/health'))).toBe(true)
  })

  it('never flags a probe running a newer agent than the server as outdated', async () => {
    mockProbes([
      { id: 'p1', name: 'Ahead', location_name: 'X', is_active: true, last_seen_at: new Date().toISOString(), version: '999.0.0', agent_status: 'current' },
    ])
    const w = await mountView()
    expect(w.text()).not.toContain(en.probes.version_outdated)
    expect(w.text()).toContain('v999.0.0')
  })
})
