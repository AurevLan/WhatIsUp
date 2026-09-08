/**
 * CertificatesPanel (F7, plan cap v2 6c) — the standalone TlsFleetView page
 * moved here verbatim (filters, table, grade badges, CSV export), reachable
 * from MonitorsView's "Certificates" view instead of its own nav entry.
 * GET /tls-fleet/ is unchanged; this only pins the panel's own rendering.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/tlsFleet', () => ({
  tlsFleetApi: {
    list: vi.fn(),
    exportCsv: vi.fn(),
  },
}))

import { tlsFleetApi } from '../src/api/tlsFleet'
import CertificatesPanel from '../src/components/monitors/CertificatesPanel.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: stub }, { path: '/monitors/:id', component: stub }],
  })
}

async function mountPanel(items = []) {
  tlsFleetApi.list.mockResolvedValue({ data: { count: items.length, items } })
  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const w = mount(CertificatesPanel, { global: { plugins: [i18n, router] } })
  await flushPromises()
  return w
}

describe('CertificatesPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the empty state when no monitor has TLS audit data yet', async () => {
    const w = await mountPanel([])
    expect(w.text()).toContain(en.tls_fleet.empty)
  })

  it('renders one row per monitor with its grade, TLS version and days remaining', async () => {
    const w = await mountPanel([
      {
        monitor_id: 'mon-1',
        monitor_name: 'shop-front',
        url: 'https://shop.example.com',
        grade: 'A',
        tls_version: 'TLSv1.3',
        cipher_name: 'TLS_AES_128_GCM_SHA256',
        san_match: true,
        days_remaining: 42,
      },
    ])
    expect(w.text()).toContain('shop-front')
    expect(w.text()).toContain('A')
    expect(w.text()).toContain('TLSv1.3')
    expect(w.text()).toContain('42')
  })

  it('reloads with the grade filter when it changes', async () => {
    const w = await mountPanel([])
    const select = w.find('select')
    await select.setValue('B')
    await flushPromises()
    expect(tlsFleetApi.list).toHaveBeenCalledWith(expect.objectContaining({ grade_below: 'B' }))
  })
})
