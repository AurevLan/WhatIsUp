/**
 * "Duplicate" button on MonitorDetailView (plan cap v2, étape 6a).
 *
 * MonitorTemplate was retired (0 rows in production, permanent nav cost for
 * a gesture nobody used through the templates UI). The gesture it served —
 * "create a monitor that looks like this one" — is kept via a Duplicate
 * action that pre-fills CreateMonitorModal, reusing the exact same
 * initial-data prop the discovery accept flow already relies on.
 *
 * Before this change the only Duplicate button in the app lived inside
 * MonitorScenarioTab, a tab rendered only for check_type === 'scenario'
 * monitors — every other check type (http, tcp, dns, …) had no way to
 * duplicate a monitor at all. This pins the button to the page header,
 * visible regardless of check_type, and checks the pre-fill it hands to
 * CreateMonitorModal: identity/state fields stripped, name suffixed.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'
import fr from '../src/i18n/fr.js'

const MONITOR = {
  id: 'mon-1',
  name: 'nginx-front-02',
  check_type: 'http',
  url: 'https://nginx-front-02.example.com',
  interval_seconds: 60,
  timeout_seconds: 10,
  tags: [],
  last_status: 'up',
  is_paused: false,
  group_id: null,
  owner_id: 'user-1',
  heartbeat_slug: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn((url) => {
      if (/^\/monitors\/mon-1$/.test(url)) return Promise.resolve({ data: MONITOR })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import MonitorDetailView from '../src/views/MonitorDetailView.vue'

// Lightweight stand-in for CreateMonitorModal: renders the prop it received
// so the test can assert on the pre-fill without mounting the real form
// (channels fetch, MonitorFormFields, …) or its own network calls.
const CreateMonitorModalStub = {
  props: { initialData: { type: Object, default: null } },
  emits: ['close', 'created'],
  template: `
    <div data-testid="create-monitor-modal">
      <pre data-testid="initial-data">{{ JSON.stringify(initialData) }}</pre>
      <button data-testid="fake-created" @click="$emit('created')">created</button>
    </div>
  `,
}

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

async function mountDetail({ locale = 'en' } = {}) {
  const router = makeRouter()
  router.push('/monitors/mon-1')
  await router.isReady()

  const i18n = createI18n({ legacy: false, locale, messages: { en, fr } })

  const wrapper = mount(MonitorDetailView, {
    global: {
      plugins: [i18n, createPinia(), router],
      stubs: {
        apexchart: true,
        ProbeMap: true,
        IncidentPlaybackMap: true,
        UptimeHeatmap: true,
        CreateMonitorModal: CreateMonitorModalStub,
      },
    },
  })
  await flush()
  return { wrapper, router }
}

describe('MonitorDetailView — Duplicate action', () => {
  it('shows a Duplicate button for a non-scenario monitor (http)', async () => {
    const { wrapper } = await mountDetail()
    const btn = wrapper.findAll('button').find((b) => b.text().includes(en.monitors.duplicate))
    expect(btn).toBeTruthy()
  })

  it('opens CreateMonitorModal pre-filled with a suffixed name and stripped identity fields', async () => {
    const { wrapper } = await mountDetail()

    expect(wrapper.find('[data-testid="create-monitor-modal"]').exists()).toBe(false)

    const btn = wrapper.findAll('button').find((b) => b.text().includes(en.monitors.duplicate))
    await btn.trigger('click')
    await flush()

    const modal = wrapper.find('[data-testid="create-monitor-modal"]')
    expect(modal.exists()).toBe(true)

    const payload = JSON.parse(wrapper.find('[data-testid="initial-data"]').text())
    expect(payload.name).toBe(en.monitors.duplicate_name_prefix.replace('{name}', MONITOR.name))
    expect(payload.check_type).toBe('http')
    expect(payload.url).toBe(MONITOR.url)
    // Identity / server-owned / state fields must not carry over to the clone.
    for (const field of [
      'id',
      'created_at',
      'updated_at',
      'owner_id',
      'heartbeat_slug',
      'last_status',
      'is_paused',
      'group_id',
    ]) {
      expect(payload).not.toHaveProperty(field)
    }
  })

  it('closes the modal and navigates back to the monitors list once the clone is created', async () => {
    const { wrapper, router } = await mountDetail()

    const btn = wrapper.findAll('button').find((b) => b.text().includes(en.monitors.duplicate))
    await btn.trigger('click')
    await flush()

    await wrapper.find('[data-testid="fake-created"]').trigger('click')
    await flush()

    expect(wrapper.find('[data-testid="create-monitor-modal"]').exists()).toBe(false)
    expect(router.currentRoute.value.path).toBe('/monitors')
  })

  it('translates the button label in French', async () => {
    const { wrapper } = await mountDetail({ locale: 'fr' })
    const btn = wrapper.findAll('button').find((b) => b.text().includes(fr.monitors.duplicate))
    expect(btn).toBeTruthy()
  })
})
