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
    probeGroups: { list: vi.fn() },
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

async function mountView({ sources = [], services = [], probes = [], probeGroups = [] } = {}) {
  discoveryApi.sources.list.mockResolvedValue({ data: sources })
  discoveryApi.services.list.mockResolvedValue({ data: services })
  discoveryApi.probeGroups.list.mockResolvedValue({ data: probeGroups })
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

  // ── Pedagogy (plan E, E-3) ────────────────────────────────────────────────

  it('explains the 3-step pipeline in the empty state', async () => {
    const w = await mountView()
    await w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)?.trigger('click')
    await flushPromises()
    expect(w.text()).toContain(en.discovery.empty_pipeline_step1)
    expect(w.text()).toContain(en.discovery.empty_pipeline_step2)
    expect(w.text()).toContain(en.discovery.empty_pipeline_step3)
  })

  it('drops the pipeline explainer once a source exists', async () => {
    const w = await mountSourcesTab([source()])
    expect(w.text()).not.toContain(en.discovery.empty_pipeline_step1)
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

  // ── Group targeting (plan E, E-2) ────────────────────────────────────────

  it('shows the probe group name instead of a probe for a group-targeted source', async () => {
    const w = await mountView({
      sources: [source({ probe_id: null, probe_group_id: 'g-1', group_capable_probe_count: 2 })],
      probeGroups: [{ id: 'g-1', name: 'internal-hosts', capabilities: ['docker'], probe_count: 3 }],
    })
    const sourcesTab = w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)
    await sourcesTab.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('internal-hosts')
  })

  it('warns when a group-targeted source has zero capable probes', async () => {
    const w = await mountView({
      sources: [source({ probe_id: null, probe_group_id: 'g-1', group_capable_probe_count: 0 })],
      probeGroups: [{ id: 'g-1', name: 'internal-hosts', capabilities: [], probe_count: 1 }],
    })
    const sourcesTab = w.findAll('button').find((b) => b.text() === en.discovery.tab_sources)
    await sourcesTab.trigger('click')
    await flushPromises()
    expect(w.text()).toContain(en.discovery.group_capacity_warning)
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

  // Chantier ergonomie, item 7c: startScanPolling() used to bail out early
  // when a poll was already running, without touching the deadline — a
  // second scan queued late in the first one's 120s budget inherited
  // whatever was left of it, and its own spinner could time out before the
  // scan it was tracking ever produced a result.
  it('gives a scan its own full budget even when it joins an already-running poll', async () => {
    vi.useFakeTimers()
    try {
      const srcA = source({ id: 's-1', last_scan_at: null })
      const srcB = source({ id: 's-2', last_scan_at: null })
      // last_scan_at never changes for either source: the only thing that can
      // end polling here is the deadline, which is exactly what's under test.
      discoveryApi.sources.list.mockResolvedValue({ data: [srcA, srcB] })
      discoveryApi.sources.scanNow.mockResolvedValue({ data: { status: 'queued' } })
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

      // Both sources render identically (same fixture target); select by order.
      const scanButtons = () => w.findAll('button').filter((b) => b.text().includes(en.discovery.scan_now))

      // Start scanning the first source.
      await scanButtons()[0].trigger('click')
      await flushPromises()

      // Run the shared poll almost to its original deadline (120s) without
      // the first scan ever completing.
      await vi.advanceTimersByTimeAsync(116000)
      await flushPromises()

      // Now queue the second source's scan, late into the first poll's life.
      const pendingButtons = () => w.findAll('button').filter((b) => b.text().includes(en.discovery.scan_pending))
      const stillNow = () => w.findAll('button').filter((b) => b.text().includes(en.discovery.scan_now))
      expect(stillNow().length).toBe(1) // the second source hasn't been scanned yet
      await stillNow()[0].trigger('click')
      await flushPromises()
      expect(pendingButtons().length).toBe(2)

      // Cross the *original* deadline (120s from the first scan). Without the
      // fix this tick clears both as "timed out"; with it, the shared
      // deadline was pushed out by the second scan's own start time.
      await vi.advanceTimersByTimeAsync(8000)
      await flushPromises()

      expect(pendingButtons().length).toBe(2)
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

  // Chantier ergonomie, item 6: the Review tab's empty state used to have no
  // CTA and no doc link, unlike the fully-fledged one on the Sources tab.
  it('offers to create a source when there is nothing to review and no source exists', async () => {
    const w = await mountView({ services: [], sources: [] })
    expect(w.text()).toContain(en.discovery.add_source)
    expect(w.find('a[href*="automatic-discovery"]').exists()).toBe(true)

    const cta = w.findAll('button').find((b) => b.text().includes(en.discovery.add_source))
    await cta.trigger('click')
    // The create-source modal opens directly from the review tab's empty state.
    expect(w.find('.modal-title').text()).toBe(en.discovery.add_source)
  })

  it('points at the sources tab when sources exist but none produced a proposal', async () => {
    const w = await mountView({ services: [], sources: [source()] })
    expect(w.text()).toContain(en.discovery.view_sources_cta)

    const cta = w.findAll('button').find((b) => b.text() === en.discovery.view_sources_cta)
    await cta.trigger('click')
    await flushPromises()
    // Switched to the sources tab: the review-only status/source filters are
    // gone, and the source registered above is now listed.
    expect(w.find('select').exists()).toBe(false)
    expect(w.text()).toContain(en.discovery.source_type_docker)
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
