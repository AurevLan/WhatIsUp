/**
 * MonitorsView — "orphaned" badge (plan D, D-3).
 *
 * A monitor whose discovered target disappeared from its discovery source
 * gets flagged in both the card (< md) and table (>= md) layouts — one
 * `GET /discovery/services?status=orphaned` call per view, never a request
 * per monitor, and never a crash when that call fails (a user without
 * discovery access must simply see no badges).
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

const getMock = vi.fn()

vi.mock('../src/api/client', () => ({
  default: {
    get: (...args) => getMock(...args),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({}),
  },
}))

import MonitorsView from '../src/views/MonitorsView.vue'

function makeMonitor(overrides = {}) {
  return {
    id: 'mon-1',
    name: 'API prod',
    url: 'https://example.com',
    check_type: 'http',
    enabled: true,
    interval_seconds: 60,
    last_status: 'up',
    uptime_24h: 99.9,
    has_open_incident: false,
    last_response_time_ms: 120,
    sparkline: [100, 110, 120],
    ...overrides,
  }
}

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: stub },
      { path: '/monitors/:id', component: stub },
      { path: '/:pathMatch(.*)*', component: stub },
    ],
  })
}

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

async function mountView({ monitors = [makeMonitor()], orphaned = [], orphanedFails = false } = {}) {
  getMock.mockImplementation((url) => {
    if (url === '/monitors/') return Promise.resolve({ data: monitors })
    if (url === '/discovery/services/') {
      return orphanedFails
        ? Promise.reject(new Error('boom'))
        : Promise.resolve({ data: orphaned })
    }
    return Promise.resolve({ data: [] })
  })

  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

  const wrapper = mount(MonitorsView, {
    global: {
      plugins: [i18n, createPinia(), router],
      stubs: {
        CreateMonitorWizard: true,
        CreateMonitorModal: true,
        EditMonitorModal: true,
        SparklineCell: true,
      },
    },
  })
  await flush()
  return wrapper
}

describe('MonitorsView — orphaned badge', () => {
  it('shows the orphaned badge for a monitor present in the orphaned services list', async () => {
    const w = await mountView({
      monitors: [makeMonitor({ id: 'mon-1' })],
      orphaned: [{ id: 'svc-1', monitor_id: 'mon-1' }],
    })
    expect(getMock).toHaveBeenCalledWith('/discovery/services/', {
      skipErrorToast: true,
      params: { status: 'orphaned' },
    })
    expect(w.text()).toContain(en.discovery.orphaned_badge)
  })

  it('does not show the badge for a monitor absent from the orphaned list', async () => {
    const w = await mountView({
      monitors: [makeMonitor({ id: 'mon-1' })],
      orphaned: [{ id: 'svc-1', monitor_id: 'mon-2' }],
    })
    expect(w.text()).not.toContain(en.discovery.orphaned_badge)
  })

  it('renders with zero badges and does not crash when the discovery call fails', async () => {
    const w = await mountView({
      monitors: [makeMonitor({ id: 'mon-1' })],
      orphanedFails: true,
    })
    expect(w.text()).not.toContain(en.discovery.orphaned_badge)
    // The monitor itself still rendered — the failure didn't take the page down.
    expect(w.text()).toContain('API prod')
  })
})
