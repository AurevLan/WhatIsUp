/**
 * Plan cap V2, 3b — the public status page shows the network verdict.
 *
 * "Is it them, or is it me?" only gets an answer on the visitor's screen when
 * an incident is open and the backend sent counters. A resolved incident, or
 * one with no verdict at all, must not surface a number computed from the
 * fleet's *current* state — see CLAUDE.md and `api/v1/public.py`.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import en from '../src/i18n/en.js'

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    useRoute: () => ({ params: { slug: 'pubgroup' }, query: {} }),
  }
})

vi.mock('../src/api/public', () => ({
  publicApi: {
    getPage: vi.fn(),
    getMonitors: vi.fn(),
    getStatus: vi.fn(),
  },
}))

import { publicApi } from '../src/api/public'
import PublicPageView from '../src/views/PublicPageView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

class MockWebSocket {
  constructor(url) {
    this.url = url
    this.onopen = null
    this.onmessage = null
    this.onclose = null
    this.onerror = null
  }
  close() {}
}

let originalWS

beforeEach(() => {
  setActivePinia(createPinia())
  originalWS = globalThis.WebSocket
  globalThis.WebSocket = MockWebSocket
  publicApi.getPage.mockResolvedValue({ data: { name: 'PubGroup' } })
  publicApi.getMonitors.mockResolvedValue({ data: [] })
})

afterEach(() => {
  globalThis.WebSocket = originalWS
  vi.clearAllMocks()
})

function baseIncident(overrides = {}) {
  return {
    id: 'inc-1',
    monitor_id: 'mon-1',
    monitor_name: 'API',
    started_at: '2026-09-01T10:00:00Z',
    resolved_at: null,
    duration_minutes: null,
    scope: 'geographic',
    is_resolved: false,
    ...overrides,
  }
}

async function render(incidents) {
  publicApi.getStatus.mockResolvedValue({ data: { incidents_30d: incidents } })
  const w = mount(PublicPageView, { global: { plugins: [i18n] } })
  await flushPromises()
  return w
}

describe('PublicPageView — network verdict', () => {
  it('shows the reachability sentence for an open incident with counters', async () => {
    const w = await render([
      baseIncident({
        network_verdict: 'network_partition_asn',
        reachable_probes: 2,
        total_probes: 3,
      }),
    ])
    expect(w.text()).toContain('responding from 2 of our 3 observation points')
  })

  it('shows nothing extra when the incident carries no verdict', async () => {
    const w = await render([baseIncident()])
    expect(w.text()).not.toContain('observation points')
    expect(w.text()).not.toContain('Some networks appear')
  })

  it('shows the category without a count for a resolved partitioned incident', async () => {
    const w = await render([
      baseIncident({
        is_resolved: true,
        resolved_at: '2026-09-01T11:00:00Z',
        duration_minutes: 60,
        network_verdict: 'network_partition_geo',
      }),
    ])
    expect(w.text()).toContain('appeared to be affected during this incident')
    expect(w.text()).not.toContain('observation points')
  })
})
