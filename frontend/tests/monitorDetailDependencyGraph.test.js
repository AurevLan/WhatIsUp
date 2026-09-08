/**
 * F6, plan cap v2 6c — the dependency graph folded into MonitorDetailView.
 *
 * DependencyGraphView (a 44-line wrapper around <DependencyGraph>, and an
 * entire permanent nav entry for it) was retired: "what depends on what" is
 * a reading done from a monitor or an incident, not a destination. This pins
 * two things on the monitor side: the graph stays collapsed until asked for
 * (no extra network call, no layout cost, on every monitor page load), and
 * the TLS grade (A-F) — previously visible only on the retired /tls-fleet
 * page — is now shown on the monitor's own SSL card.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

const MONITOR = {
  id: 'mon-1',
  name: 'shop-front',
  check_type: 'http',
  url: 'https://shop.example.com',
  interval_seconds: 60,
  timeout_seconds: 10,
  tags: [],
  last_status: 'up',
  is_paused: false,
  group_id: null,
  ssl_check_enabled: true,
  ssl_expiry_warn_days: 30,
  owner_id: 'user-1',
  heartbeat_slug: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

const SSL_RESULT = {
  id: 'res-1',
  monitor_id: 'mon-1',
  probe_id: 'probe-1',
  checked_at: '2026-09-01T00:00:00Z',
  status: 'up',
  ssl_valid: true,
  ssl_expires_at: '2026-12-01T00:00:00Z',
  ssl_days_remaining: 60,
  tls_audit: { grade: 'B', tls_version: 'TLSv1.3', cipher_name: 'TLS_AES_128_GCM_SHA256', san_match: true },
}

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn((url) => {
      if (/^\/monitors\/mon-1$/.test(url)) return Promise.resolve({ data: MONITOR })
      if (/^\/monitors\/mon-1\/results/.test(url)) return Promise.resolve({ data: [SSL_RESULT] })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import MonitorDetailView from '../src/views/MonitorDetailView.vue'

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/monitors', component: stub },
      { path: '/monitors/:id', component: stub },
      { path: '/:pathMatch(.*)*', component: stub },
    ],
  })
}

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

async function mountDetail() {
  const router = makeRouter()
  router.push('/monitors/mon-1')
  await router.isReady()
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

  const wrapper = mount(MonitorDetailView, {
    global: {
      plugins: [i18n, createPinia(), router],
      stubs: {
        apexchart: true,
        ProbeMap: true,
        IncidentPlaybackMap: true,
        UptimeHeatmap: true,
        // The real DependencyGraph fetches /monitors/graph and runs a force
        // simulation — irrelevant here, and noisy under jsdom.
        DependencyGraph: { template: '<div data-testid="dep-graph-stub" />' },
      },
    },
  })
  await flush()
  return wrapper
}

describe('MonitorDetailView — dependency graph (F6)', () => {
  it('keeps the graph collapsed by default', async () => {
    const w = await mountDetail()
    expect(w.find('[data-testid="dep-graph-stub"]').exists()).toBe(false)
    expect(w.text()).toContain(en.graph.title)
  })

  it('reveals the graph once the toggle is clicked', async () => {
    const w = await mountDetail()
    const toggle = w.findAll('button').find((b) => b.text().includes(en.graph.title))
    expect(toggle).toBeTruthy()
    await toggle.trigger('click')
    await flush()
    expect(w.find('[data-testid="dep-graph-stub"]').exists()).toBe(true)
  })

  it('shows the TLS grade on the monitor SSL card (F7 reserve)', async () => {
    const w = await mountDetail()
    expect(w.text()).toContain('B')
    expect(w.text()).toContain(en.tls_fleet.col_grade)
  })
})
