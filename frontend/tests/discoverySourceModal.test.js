/**
 * DiscoverySourceModal (plan D, D-3) — the source form only ever offers a
 * source_type the selected probe actually declared runnable at its last
 * heartbeat. A probe declaring none must say so explicitly, never render a
 * silently empty <select>.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/discovery', () => ({
  discoveryApi: {
    sources: { create: vi.fn(), update: vi.fn() },
  },
}))

import { discoveryApi } from '../src/api/discovery'
import DiscoverySourceModal from '../src/components/discovery/DiscoverySourceModal.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const probes = [
  {
    id: 'p-docker',
    name: 'docker-probe',
    discovery_capabilities: ['docker', 'port_scan', 'dns_zone'],
  },
  { id: 'p-none', name: 'legacy-probe', discovery_capabilities: [] },
  { id: 'p-null', name: 'pre-d1-probe', discovery_capabilities: null },
]

// plan E, E-2 — union of member capabilities, computed server-side.
const probeGroups = [
  { id: 'g-mixed', name: 'mixed-group', capabilities: ['docker', 'port_scan'], probe_count: 2 },
  { id: 'g-empty', name: 'empty-group', capabilities: [], probe_count: 1 },
]

function mountModal(props = {}) {
  return mount(DiscoverySourceModal, {
    props: { probes, probeGroups, source: null, ...props },
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
}

function selectTargetMode(w, mode) {
  return w.findAll('input[type="radio"]').find((r) => r.element.value === mode).setValue()
}

describe('DiscoverySourceModal', () => {
  beforeEach(() => vi.clearAllMocks())

  it('prompts to pick a probe before offering any source type', () => {
    const w = mountModal()
    expect(w.text()).toContain(en.discovery.pick_probe_first)
  })

  it('offers only the source types the selected probe declared', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-docker')
    const options = w.findAll('select')[1].findAll('option').map((o) => o.element.value)
    expect(options).toEqual(expect.arrayContaining(['docker', 'port_scan', 'dns_zone']))
  })

  it('says explicitly a probe with an empty capability list can discover nothing', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-none')
    expect(w.text()).toContain('legacy-probe')
    expect(w.find('select').exists()).toBe(true)
    // No second <select> for source_type — replaced by the explicit warning.
    expect(w.findAll('select').length).toBe(1)
  })

  it('links to the docs on how to enable capabilities (plan E, E-3)', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-none')
    expect(w.text()).toContain(en.discovery.no_capabilities_hint)
    const link = w.find('a[href="https://github.com/AurevLan/whatisup#automatic-discovery"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('target')).toBe('_blank')
  })

  it('treats a null discovery_capabilities (pre-D1 probe) the same as empty', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-null')
    expect(w.findAll('select').length).toBe(1)
  })

  it('edit mode locks the probe and source_type, only params/enabled are editable', () => {
    const source = {
      id: 's-1',
      probe_id: 'p-docker',
      source_type: 'port_scan',
      params: { cidr: '10.0.0.0/24', ports: [80, 443] },
      enabled: true,
    }
    const w = mountModal({ source })
    expect(w.find('select').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain(en.discovery.source_type_port_scan)
    expect(w.find('input[placeholder="10.0.0.0/24"]').exists()).toBe(true)
  })

  it('submits a port_scan create with parsed ports', async () => {
    discoveryApi.sources.create.mockResolvedValue({ data: { id: 'new' } })
    const w = mountModal()
    await w.find('select').setValue('p-docker')
    await w.findAll('select')[1].setValue('port_scan')
    // Positional `inputs[0]`/`inputs[1]` would now hit the targeting radios
    // (plan E, E-2) — select the cidr/ports fields by placeholder instead,
    // same as the dns_zone test below.
    await w.find('input[placeholder="10.0.0.0/24"]').setValue('10.0.0.0/24')
    await w.find('input[placeholder="22, 80, 443"]').setValue('22, 80, 443')
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(discoveryApi.sources.create).toHaveBeenCalledWith(
      {
        probe_id: 'p-docker',
        source_type: 'port_scan',
        params: { cidr: '10.0.0.0/24', ports: [22, 80, 443] },
        enabled: true,
      },
      { skipErrorToast: true }
    )
    expect(w.emitted('saved')).toBeTruthy()
  })

  it('dns_zone form defaults to all three record types checked', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-docker')
    await w.findAll('select')[1].setValue('dns_zone')
    const checkboxes = w.findAll('input[type="checkbox"]').filter((c) =>
      ['A', 'AAAA', 'CNAME'].includes(c.element.value)
    )
    expect(checkboxes).toHaveLength(3)
    expect(checkboxes.every((c) => c.element.checked)).toBe(true)
  })

  it('submits a dns_zone create with zone/resolver/record_types', async () => {
    discoveryApi.sources.create.mockResolvedValue({ data: { id: 'new' } })
    const w = mountModal()
    await w.find('select').setValue('p-docker')
    await w.findAll('select')[1].setValue('dns_zone')
    await w.find('input[placeholder="example.com"]').setValue('example.com')
    await w.find('input[placeholder="203.0.113.10"]').setValue('203.0.113.10')
    // Uncheck AAAA — only A and CNAME requested.
    const aaaa = w.findAll('input[type="checkbox"]').find((c) => c.element.value === 'AAAA')
    await aaaa.setValue(false)
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(discoveryApi.sources.create).toHaveBeenCalledWith(
      {
        probe_id: 'p-docker',
        source_type: 'dns_zone',
        params: { zone: 'example.com', resolver: '203.0.113.10', record_types: ['A', 'CNAME'] },
        enabled: true,
      },
      { skipErrorToast: true }
    )
    expect(w.emitted('saved')).toBeTruthy()
  })

  it('dns_zone edit mode locks probe/source_type, shows saved params', () => {
    const source = {
      id: 's-2',
      probe_id: 'p-docker',
      source_type: 'dns_zone',
      params: { zone: 'example.com', resolver: '203.0.113.10', record_types: ['A'] },
      enabled: true,
    }
    const w = mountModal({ source })
    expect(w.find('select').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain(en.discovery.source_type_dns_zone)
    expect(w.find('input[placeholder="example.com"]').element.value).toBe('example.com')
    expect(w.find('input[placeholder="203.0.113.10"]').element.value).toBe('203.0.113.10')
  })

  it('dns_zone cannot submit without zone/resolver', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-docker')
    await w.findAll('select')[1].setValue('dns_zone')
    expect(w.find('button[type="submit"]').attributes('disabled')).toBeDefined()
  })

  // ── Group targeting (plan E, E-2) ──────────────────────────────────────

  it('defaults to probe targeting, with a probe select as the first field', () => {
    const w = mountModal()
    expect(w.text()).toContain(en.discovery.pick_probe_first)
    expect(w.find('select').exists()).toBe(true)
  })

  it('switching to group mode offers the group select and its member capabilities', async () => {
    const w = mountModal()
    await selectTargetMode(w, 'group')
    expect(w.text()).toContain(en.discovery.pick_group_first)

    await w.find('select').setValue('g-mixed')
    const typeOptions = w.findAll('select')[1].findAll('option').map((o) => o.element.value)
    expect(typeOptions).toEqual(expect.arrayContaining(['docker', 'port_scan']))
    expect(typeOptions).not.toContain('dns_zone')
  })

  it('says explicitly a group with no capable member can discover nothing', async () => {
    const w = mountModal()
    await selectTargetMode(w, 'group')
    await w.find('select').setValue('g-empty')
    expect(w.text()).toContain('empty-group')
    expect(w.findAll('select').length).toBe(1)
  })

  it('shows an execution hint for a group-targeted docker source (fan-out)', async () => {
    const w = mountModal()
    await selectTargetMode(w, 'group')
    await w.find('select').setValue('g-mixed')
    await w.findAll('select')[1].setValue('docker')
    expect(w.text()).toContain(en.discovery.group_hint_docker)
  })

  it('shows an execution hint for a group-targeted port_scan source (elected)', async () => {
    const w = mountModal()
    await selectTargetMode(w, 'group')
    await w.find('select').setValue('g-mixed')
    await w.findAll('select')[1].setValue('port_scan')
    expect(w.text()).toContain(en.discovery.group_hint_port_scan)
  })

  it('submits a group-targeted docker create with probe_group_id, no probe_id', async () => {
    discoveryApi.sources.create.mockResolvedValue({ data: { id: 'new' } })
    const w = mountModal()
    await selectTargetMode(w, 'group')
    await w.find('select').setValue('g-mixed')
    await w.findAll('select')[1].setValue('docker')
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(discoveryApi.sources.create).toHaveBeenCalledWith(
      { probe_group_id: 'g-mixed', source_type: 'docker', params: {}, enabled: true },
      { skipErrorToast: true }
    )
  })

  it('edit mode locks the targeting radios and never resends probe_id/probe_group_id', async () => {
    discoveryApi.sources.update.mockResolvedValue({ data: { id: 's-1' } })
    const source = {
      id: 's-1',
      probe_id: 'p-docker',
      probe_group_id: null,
      source_type: 'docker',
      params: {},
      enabled: true,
    }
    const w = mountModal({ source })
    for (const radio of w.findAll('input[type="radio"]')) {
      expect(radio.attributes('disabled')).toBeDefined()
    }
    await w.find('form').trigger('submit')
    await flushPromises()

    expect(discoveryApi.sources.update).toHaveBeenCalledWith(
      's-1',
      { params: {}, enabled: true },
      { skipErrorToast: true }
    )
  })

  it('edit mode of a group-targeted source shows the group name, not a probe select', () => {
    const source = {
      id: 's-2',
      probe_id: null,
      probe_group_id: 'g-mixed',
      source_type: 'docker',
      params: {},
      enabled: true,
    }
    const w = mountModal({ source })
    expect(w.text()).toContain('mixed-group')
    expect(w.find('select').attributes('disabled')).toBeDefined()
  })
})
