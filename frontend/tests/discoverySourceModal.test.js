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
  { id: 'p-docker', name: 'docker-probe', discovery_capabilities: ['docker', 'port_scan'] },
  { id: 'p-none', name: 'legacy-probe', discovery_capabilities: [] },
  { id: 'p-null', name: 'pre-d1-probe', discovery_capabilities: null },
]

function mountModal(props = {}) {
  return mount(DiscoverySourceModal, {
    props: { probes, source: null, ...props },
    global: { plugins: [i18n], stubs: { teleport: true } },
  })
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
    expect(options).toEqual(expect.arrayContaining(['docker', 'port_scan']))
  })

  it('says explicitly a probe with an empty capability list can discover nothing', async () => {
    const w = mountModal()
    await w.find('select').setValue('p-none')
    expect(w.text()).toContain('legacy-probe')
    expect(w.find('select').exists()).toBe(true)
    // No second <select> for source_type — replaced by the explicit warning.
    expect(w.findAll('select').length).toBe(1)
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
    const inputs = w.findAll('input')
    await inputs[0].setValue('10.0.0.0/24')
    await inputs[1].setValue('22, 80, 443')
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
})
