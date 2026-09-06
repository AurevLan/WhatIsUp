/**
 * Plan cap V2, 5b — status page announcements on the public page.
 *
 * Decisions under test (see plan_cap_v2.md § 5b and CLAUDE.md "Deux familles
 * d'incidents"): an announcement is a human narration, never an Incident.
 * It renders alongside its update thread in order, and a closed one stays
 * visible without being presented as active.
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

async function render(announcements) {
  publicApi.getStatus.mockResolvedValue({
    data: { incidents_30d: [], maintenance_windows: [], announcements },
  })
  const w = mount(PublicPageView, { global: { plugins: [i18n] } })
  await flushPromises()
  return w
}

describe('PublicPageView — status announcements', () => {
  it('renders an active announcement with its update thread in order', async () => {
    const w = await render([
      {
        id: 'a1',
        title: 'Investigating reported slowness',
        status: 'investigating',
        started_at: new Date(Date.now() - 3_600_000).toISOString(),
        ended_at: null,
        is_active: true,
        updates: [
          {
            id: 'u1',
            status: 'investigating',
            message: 'We are looking into user reports.',
            created_at: new Date(Date.now() - 3_600_000).toISOString(),
          },
          {
            id: 'u2',
            status: 'identified',
            message: 'Root cause found.',
            created_at: new Date(Date.now() - 1_800_000).toISOString(),
          },
        ],
      },
    ])
    expect(w.text()).toContain('Investigating reported slowness')
    const html = w.html()
    const idxFirst = html.indexOf('We are looking into user reports.')
    const idxSecond = html.indexOf('Root cause found.')
    expect(idxFirst).toBeGreaterThan(-1)
    expect(idxSecond).toBeGreaterThan(idxFirst)
    expect(w.text()).not.toContain('Closed')
  })

  it('shows a closed announcement without presenting it as active', async () => {
    const w = await render([
      {
        id: 'a2',
        title: 'Past slowness incident',
        status: 'resolved',
        started_at: new Date(Date.now() - 7_200_000).toISOString(),
        ended_at: new Date(Date.now() - 3_600_000).toISOString(),
        is_active: false,
        updates: [
          {
            id: 'u3',
            status: 'resolved',
            message: 'All clear.',
            created_at: new Date(Date.now() - 3_600_000).toISOString(),
          },
        ],
      },
    ])
    expect(w.text()).toContain('Past slowness incident')
    expect(w.text()).toContain('Closed')
  })

  it('renders nothing when there are no announcements', async () => {
    const w = await render([])
    expect(w.text()).not.toContain('announcement')
  })
})
