/**
 * DiscoveryView (plan D, D-3) — sources tab + review tab (bulk accept/dismiss,
 * per-row actions). Mirrors the mocking pattern of oncallView.test.js: mock
 * the api modules directly rather than the axios client.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/discovery', () => ({
  discoveryApi: {
    sources: { list: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(), scanNow: vi.fn() },
    services: { list: vi.fn(), accept: vi.fn(), dismiss: vi.fn(), bulk: vi.fn() },
  },
}))
vi.mock('../src/api/probes', () => ({
  probesApi: { list: vi.fn() },
}))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))
vi.mock('../src/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}))

import { discoveryApi } from '../src/api/discovery'
import { probesApi } from '../src/api/probes'
import DiscoveryView from '../src/views/DiscoveryView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

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

function source(overrides = {}) {
  return {
    id: 's-1',
    probe_id: 'p-1',
    source_type: 'docker',
    params: {},
    enabled: true,
    last_scan_at: null,
    last_scan_target_count: null,
    last_scan_probe_id: null,
    ...overrides,
  }
}

function service(overrides = {}) {
  return {
    id: 'svc-1',
    source_id: 's-1',
    monitor_id: null,
    host: '10.0.0.5',
    port: 80,
    proto: 'tcp',
    normalized_target: 'tcp://10.0.0.5:80',
    hints: {},
    status: 'proposed',
    dismissed_reason: null,
    suggested_check_type: 'http',
    suggested_name: '10.0.0.5:80',
    suggested_group: null,
    suggested_tags: ['discovery:docker'],
    suggested_alert_matrix_template_id: null,
    ...overrides,
  }
}

async function mountView({ sources = [], services = [], probes = [] } = {}) {
  discoveryApi.sources.list.mockResolvedValue({ data: sources })
  discoveryApi.services.list.mockResolvedValue({ data: services })
  probesApi.list.mockResolvedValue({ data: probes })

  const router = makeRouter()
  router.push('/')
  await router.isReady()

  const w = mount(DiscoveryView, {
    global: { plugins: [i18n, createPinia(), router], stubs: { teleport: true } },
  })
  await flushPromises()
  return w
}

describe('DiscoveryView — sources tab', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the empty state when there are no sources', async () => {
    const w = await mountView()
    await w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)?.trigger('click')
    await flushPromises()
    expect(w.text()).toContain(en.discovery.no_sources)
  })

  it('lists a source with its probe name and enabled state', async () => {
    const w = await mountView({
      sources: [source()],
      probes: [{ id: 'p-1', name: 'docker-probe', discovery_capabilities: ['docker'] }],
    })
    const sourcesTab = w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)
    await sourcesTab.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('docker-probe')
    expect(w.text()).toContain(en.discovery.enabled_label)
  })

  // ── Scan feedback (plan E, E-1) ──────────────────────────────────────────

  async function mountSourcesTab(sources) {
    const w = await mountView({ sources, probes: [{ id: 'p-1', name: 'docker-probe' }] })
    const sourcesTab = w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)
    await sourcesTab.trigger('click')
    await flushPromises()
    return w
  }

  it('shows "never scanned" for a source with no last_scan_at', async () => {
    const w = await mountSourcesTab([source({ last_scan_at: null })])
    expect(w.text()).toContain(en.discovery.never_scanned)
  })

  it('shows the last scan time and target count for a scanned source', async () => {
    const w = await mountSourcesTab([
      source({ last_scan_at: new Date().toISOString(), last_scan_target_count: 3 }),
    ])
    expect(w.text()).not.toContain(en.discovery.never_scanned)
    expect(w.text()).toContain('3 targets found')
  })

  it('clicking "Scan now" queues a scan and shows a pending state', async () => {
    // Left unresolved on purpose — pending state must show up optimistically,
    // synchronously with the click, not only once the request round-trips.
    discoveryApi.sources.scanNow.mockReturnValue(new Promise(() => {}))
    const src = source({ last_scan_at: null })
    const w = await mountSourcesTab([src])

    const scanBtn = w.findAll('button').find((b) => b.text().includes(en.discovery.scan_now))
    expect(scanBtn.attributes('disabled')).toBeUndefined()
    await scanBtn.trigger('click')

    expect(discoveryApi.sources.scanNow).toHaveBeenCalledWith('s-1', { skipErrorToast: true })
    expect(w.text()).toContain(en.discovery.scan_pending)
    const pendingBtn = w.findAll('button').find((b) => b.text().includes(en.discovery.scan_pending))
    expect(pendingBtn.attributes('disabled')).toBeDefined()
  })

  it('clears the pending state once polling observes a new last_scan_at', async () => {
    vi.useFakeTimers()
    try {
      discoveryApi.sources.scanNow.mockResolvedValue({
        data: { status: 'queued', source_id: 's-1' },
      })
      const src = source({ last_scan_at: null, last_scan_target_count: null })
      discoveryApi.sources.list
        .mockResolvedValueOnce({ data: [src] })
        .mockResolvedValueOnce({
          data: [{ ...src, last_scan_at: '2026-08-29T12:00:00Z', last_scan_target_count: 1 }],
        })
      discoveryApi.services.list.mockResolvedValue({ data: [] })

      const router = makeRouter()
      router.push('/')
      await router.isReady()
      const w = mount(DiscoveryView, {
        global: { plugins: [i18n, createPinia(), router], stubs: { teleport: true } },
      })
      await flushPromises()

      const sourcesTab = w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)
      await sourcesTab.trigger('click')
      await flushPromises()

      const scanBtn = w.findAll('button').find((b) => b.text().includes(en.discovery.scan_now))
      await scanBtn.trigger('click')
      await flushPromises()
      expect(w.text()).toContain(en.discovery.scan_pending)

      await vi.advanceTimersByTimeAsync(4000)
      await flushPromises()

      expect(w.text()).not.toContain(en.discovery.scan_pending)
      expect(w.text()).toContain(en.discovery.scan_now)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('DiscoveryView — review tab', () => {
  beforeEach(() => vi.clearAllMocks())

  it('defaults to the review tab and lists proposed services', async () => {
    const w = await mountView({ services: [service()] })
    expect(w.text()).toContain('10.0.0.5:80')
    expect(w.text()).toContain(en.discovery.status_proposed)
  })

  it('shows the empty state when there is nothing to review', async () => {
    const w = await mountView({ services: [] })
    expect(w.text()).toContain(en.discovery.no_services)
  })

  it('links an orphaned service to its monitor', async () => {
    const w = await mountView({
      services: [service({ id: 'svc-2', status: 'orphaned', monitor_id: 'mon-42' })],
    })
    const link = w.find(`a[href="/monitors/mon-42"]`)
    expect(link.exists()).toBe(true)
  })

  it('bulk-dismisses the selection with the shared reason', async () => {
    discoveryApi.services.bulk.mockResolvedValue({
      data: { results: [{ service_id: 'svc-1', ok: true, detail: null, service: service({ status: 'dismissed' }) }] },
    })
    const w = await mountView({ services: [service()] })

    // Grab the row checkbox (skip the select-all header checkbox).
    const rowCheckbox = w.findAll('tbody input[type="checkbox"]')[0]
    await rowCheckbox.setValue(true)

    const dismissBtn = w.findAll('button').find((b) => b.text().includes(en.discovery.bulk_dismiss))
    await dismissBtn.trigger('click')
    await flushPromises()

    // The reason modal is open — fill it and confirm. Scoped to the dialog:
    // per-row "Dismiss" buttons in the list share the same label.
    const dialog = w.find('[role="dialog"]')
    const textarea = dialog.find('textarea')
    await textarea.setValue('decommissioned')
    const confirmBtn = dialog.findAll('button').find((b) => b.text() === en.discovery.dismiss)
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(discoveryApi.services.bulk).toHaveBeenCalledWith(
      { action: 'dismiss', service_ids: ['svc-1'], reason: 'decommissioned' },
      { skipErrorToast: true }
    )
  })

  it('accepts a service through the confirmation modal, overriding the name', async () => {
    discoveryApi.services.accept.mockResolvedValue({ data: service({ status: 'accepted' }) })
    const w = await mountView({ services: [service()] })

    const acceptBtn = w.findAll('button').find((b) => b.attributes('title') === en.discovery.accept)
    await acceptBtn.trigger('click')
    await flushPromises()

    const dialog = w.find('[role="dialog"]')
    const nameInput = dialog.find(`input[placeholder="${service().suggested_name}"]`)
    await nameInput.setValue('renamed-service')
    const confirmBtn = dialog.findAll('button').find((b) => b.text() === en.discovery.accept)
    await confirmBtn.trigger('click')
    await flushPromises()

    expect(discoveryApi.services.accept).toHaveBeenCalledWith(
      'svc-1',
      { interval_seconds: 60, name: 'renamed-service', check_type: 'http' },
      { skipErrorToast: true }
    )
  })
})
