/**
 * AppLayout — Discovery nav badge (plan E, E-3). Same visual mechanic as the
 * existing `downCount`/`openIncidentCount` badges: a plain `:badge` on
 * NavLink, which itself renders nothing for zero — so "no proposals" means
 * no badge, not a "0" badge.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/discovery', () => ({
  discoveryApi: {
    services: { pendingCount: vi.fn() },
  },
}))

import { discoveryApi } from '../src/api/discovery'
import AppLayout from '../src/views/layouts/AppLayout.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: stub }, { path: '/:pathMatch(.*)*', component: stub }],
  })
}

async function mountLayout() {
  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const w = mount(AppLayout, {
    global: { plugins: [i18n, createPinia(), router], stubs: { teleport: true } },
  })
  await flushPromises()
  return w
}

function discoveryLink(w) {
  return w.findAll('a').find((a) => a.text().includes(en.nav.discovery))
}

describe('AppLayout — discovery pending-proposals badge', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows no badge when there are zero pending proposals', async () => {
    discoveryApi.services.pendingCount.mockResolvedValue({ data: { count: 0 } })
    const w = await mountLayout()
    const link = discoveryLink(w)
    expect(link.find('.nav-link__badge').exists()).toBe(false)
  })

  it('shows the count as a badge when proposals are pending', async () => {
    discoveryApi.services.pendingCount.mockResolvedValue({ data: { count: 4 } })
    const w = await mountLayout()
    const link = discoveryLink(w)
    expect(link.find('.nav-link__badge').exists()).toBe(true)
    expect(link.find('.nav-link__badge').text()).toBe('4')
  })

  it('shows no badge when the count request fails', async () => {
    discoveryApi.services.pendingCount.mockRejectedValue(new Error('network'))
    const w = await mountLayout()
    const link = discoveryLink(w)
    expect(link.find('.nav-link__badge').exists()).toBe(false)
  })
})
