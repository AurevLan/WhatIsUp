/**
 * A11Y-0 — axe-core gate on the main views (plan_accessibilite.md).
 *
 * Mounts each view standalone (mock API, fresh Pinia, memory router) and
 * fails on any critical/serious axe violation. Page-level rules (region,
 * landmark-one-main, page-has-heading-one, bypass) are disabled because we
 * mount fragments without the AppLayout shell; color-contrast is disabled
 * because jsdom does not compute real styles — contrast is covered by the
 * A11Y-5 phase instead.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import axe from 'axe-core'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import LoginView from '../src/views/LoginView.vue'
import MonitorsView from '../src/views/MonitorsView.vue'
import MonitorDetailView from '../src/views/MonitorDetailView.vue'
import IncidentsView from '../src/views/IncidentsView.vue'
import AlertsView from '../src/views/AlertsView.vue'
import SettingsView from '../src/views/SettingsView.vue'

const AXE_OPTIONS = {
  resultTypes: ['violations'],
  rules: {
    'color-contrast': { enabled: false },     // jsdom: no real style computation
    region: { enabled: false },               // fragment: no AppLayout landmarks
    'landmark-one-main': { enabled: false },  // idem
    'page-has-heading-one': { enabled: false }, // idem
    bypass: { enabled: false },               // skip-link lives in AppLayout
  },
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
  // Let pending API promises + re-renders settle
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

async function runAxe(component, { path = '/' } = {}) {
  const router = makeRouter()
  router.push(path)
  await router.isReady()

  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })
  const host = document.createElement('div')
  document.body.appendChild(host)

  const wrapper = mount(component, {
    attachTo: host,
    global: {
      plugins: [i18n, createPinia(), router],
      stubs: {
        // Heavy/canvas children irrelevant to the a11y of the view itself
        apexchart: true,
        ProbeMap: true,
        IncidentPlaybackMap: true,
        UptimeHeatmap: true,
      },
    },
  })
  await flush()

  try {
    const results = await axe.run(wrapper.element, AXE_OPTIONS)
    return results.violations.filter((v) => ['critical', 'serious'].includes(v.impact))
  } finally {
    wrapper.unmount()
    host.remove()
  }
}

// Readable failure output: one line per violation with the offending nodes
function format(violations) {
  return violations.map(
    (v) =>
      `[${v.impact}] ${v.id}: ${v.help} → ${v.nodes
        .map((n) => n.html.slice(0, 120))
        .join(' | ')}`
  )
}

describe('a11y — axe gate on main views', () => {
  const cases = [
    ['LoginView', LoginView, {}],
    ['MonitorsView', MonitorsView, {}],
    ['MonitorDetailView', MonitorDetailView, { path: '/monitors/00000000-0000-0000-0000-000000000001' }],
    ['IncidentsView', IncidentsView, {}],
    ['AlertsView', AlertsView, {}],
    ['SettingsView', SettingsView, {}],
  ]

  it.each(cases)('%s has no critical/serious violations', async (_name, component, opts) => {
    const violations = await runAxe(component, opts)
    expect(format(violations)).toEqual([])
  })
})
