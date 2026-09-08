/**
 * F8, plan cap v2 6c — Audit Log moved out of the main nav into Réglages.
 *
 * The audit trail is a compliance requirement kept in full (same view, same
 * route, full history) — only how you get to it changes: from "what
 * happened", answered from Settings, instead of a permanent top-level entry
 * nobody needs on a solo instance.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import SettingsView from '../src/views/SettingsView.vue'

function makeRouter() {
  const stub = { template: '<div />' }
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: stub },
      { path: '/audit', component: stub },
      { path: '/:pathMatch(.*)*', component: stub },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })
  const w = mount(SettingsView, { global: { plugins: [i18n, createPinia(), router] } })
  await new Promise((r) => setTimeout(r, 0))
  return w
}

describe('SettingsView — audit log link (F8)', () => {
  it('shows an audit log card with a link to /audit', async () => {
    const w = await mountView()
    expect(w.text()).toContain(en.audit.title)
    const link = w.find('a[href="/audit"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain(en.settings.audit_cta)
  })
})
