/**
 * Plan cap V2, 5a — the public status page must never render "major outage"
 * for a monitor that is down because of a scheduled maintenance window.
 *
 * This is the regression the whole lot exists to forbid: `globalStatus` used
 * to be computed straight off `current_status`, so a maintenance window that
 * takes a monitor down painted the whole public page red for visitors — with
 * no way for the operator to say why. See CLAUDE.md § "Réparer la page de
 * statut" and `api/v1/public.py::get_public_status`.
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
})

afterEach(() => {
  globalThis.WebSocket = originalWS
  vi.clearAllMocks()
})

function downMonitor(overrides = {}) {
  return {
    id: 'mon-1',
    name: 'API',
    check_type: 'http',
    url: 'https://example.com',
    current_status: 'down',
    uptime_24h: 0,
    history_90d: [],
    ...overrides,
  }
}

async function render({ monitors, maintenanceWindows }) {
  publicApi.getMonitors.mockResolvedValue({ data: monitors })
  publicApi.getStatus.mockResolvedValue({
    data: { incidents_30d: [], maintenance_windows: maintenanceWindows },
  })
  const w = mount(PublicPageView, { global: { plugins: [i18n] } })
  await flushPromises()
  return w
}

describe('PublicPageView — scheduled maintenance', () => {
  it('never shows major outage for a monitor down under an active maintenance window', async () => {
    const w = await render({
      monitors: [downMonitor()],
      maintenanceWindows: [
        {
          id: 'w1',
          monitor_id: 'mon-1',
          starts_at: new Date(Date.now() - 60_000).toISOString(),
          ends_at: new Date(Date.now() + 3_600_000).toISOString(),
          message: null,
        },
      ],
    })
    expect(w.text()).not.toContain('Major outage')
    expect(w.text()).toContain('Maintenance in progress')
  })

  it('shows the operator-written public message when present', async () => {
    const w = await render({
      monitors: [downMonitor()],
      maintenanceWindows: [
        {
          id: 'w1',
          monitor_id: 'mon-1',
          starts_at: new Date(Date.now() - 60_000).toISOString(),
          ends_at: new Date(Date.now() + 3_600_000).toISOString(),
          message: 'We are upgrading our database.',
        },
      ],
    })
    expect(w.text()).toContain('We are upgrading our database.')
  })

  it('still reports a real outage on a monitor with no maintenance window', async () => {
    const w = await render({
      monitors: [downMonitor(), downMonitor({ id: 'mon-2', name: 'Web', current_status: 'up' })],
      maintenanceWindows: [],
    })
    expect(w.text()).toContain('Major outage')
    expect(w.text()).not.toContain('Maintenance in progress')
  })

  it('a group-wide window (no monitor_id) covers every monitor', async () => {
    const w = await render({
      monitors: [downMonitor(), downMonitor({ id: 'mon-2', name: 'Web' })],
      maintenanceWindows: [
        {
          id: 'w1',
          monitor_id: null,
          starts_at: new Date(Date.now() - 60_000).toISOString(),
          ends_at: new Date(Date.now() + 3_600_000).toISOString(),
          message: null,
        },
      ],
    })
    expect(w.text()).not.toContain('Major outage')
    expect(w.text()).toContain('Maintenance in progress')
  })

  it('shows an upcoming window as scheduled, without touching globalStatus', async () => {
    const w = await render({
      monitors: [downMonitor({ current_status: 'up' })],
      maintenanceWindows: [
        {
          id: 'w1',
          monitor_id: 'mon-1',
          starts_at: new Date(Date.now() + 3_600_000).toISOString(),
          ends_at: new Date(Date.now() + 7_200_000).toISOString(),
          message: null,
        },
      ],
    })
    expect(w.text()).toContain('All systems operational')
    expect(w.text()).toContain('Scheduled maintenance')
  })
})
