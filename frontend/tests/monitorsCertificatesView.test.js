/**
 * F7, plan cap v2 6c — TLS Fleet folded into MonitorsView as a "Certificates"
 * saved view (list / board / certificates), instead of a permanent top-level
 * nav entry. The endpoint (GET /tls-fleet/) is untouched — only the
 * standalone destination is retired.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

const VIEW_STORAGE_KEY = 'whatisup_monitors_view'

const MONITOR = {
  id: 'mon-1',
  name: 'API prod',
  url: 'https://example.com',
  check_type: 'http',
  enabled: true,
  interval_seconds: 60,
  last_status: 'up',
  uptime_24h: 99.9,
  has_open_incident: false,
}

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn((url) => {
      if (url === '/monitors/') return Promise.resolve({ data: [MONITOR] })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({}),
  },
}))

import MonitorsView from '../src/views/MonitorsView.vue'

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

async function mountView() {
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
        CertificatesPanel: { template: '<div data-testid="certs-panel-stub" />' },
      },
    },
  })
  await flush()
  return wrapper
}

describe('MonitorsView — Certificates view (F7)', () => {
  beforeEach(() => localStorage.removeItem(VIEW_STORAGE_KEY))
  afterEach(() => localStorage.removeItem(VIEW_STORAGE_KEY))

  it('defaults to the list view, not certificates', async () => {
    const w = await mountView()
    expect(w.find('[data-testid="certs-panel-stub"]').exists()).toBe(false)
    expect(w.find('table').exists()).toBe(true)
  })

  it('switches to the Certificates panel and hides the monitors table/filters', async () => {
    const w = await mountView()
    const toggle = w.find(`[aria-label="${en.monitors.view_certificates}"]`)
    expect(toggle.exists()).toBe(true)
    await toggle.trigger('click')
    await flush()

    expect(w.find('[data-testid="certs-panel-stub"]').exists()).toBe(true)
    expect(w.find('table').exists()).toBe(false)
    // Status chip filters are monitors-list-specific — not shown here.
    expect(w.text()).not.toContain(en.monitors.all_statuses)
  })

  it('persists the chosen view mode across mounts (existing view-mode persistence)', async () => {
    const w = await mountView()
    const toggle = w.find(`[aria-label="${en.monitors.view_certificates}"]`)
    await toggle.trigger('click')
    await flush()
    expect(localStorage.getItem(VIEW_STORAGE_KEY)).toBe('certs')
  })
})
