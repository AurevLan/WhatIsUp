/**
 * C4 (bilan 2026-07) — EmptyState rollout on 6 views that previously
 * hand-rolled their own "no data" markup (or a bare text line): Incidents,
 * ApiKeys, Templates, Audit, TlsFleet, IncidentGroups.
 *
 * Mounts each view standalone (mock API returning empty lists, fresh
 * Pinia, memory router — same harness as tests/a11y.test.js) and asserts
 * the real <EmptyState> component rendered with the expected i18n title.
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
    put: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import IncidentsView from '../src/views/IncidentsView.vue'
import ApiKeysView from '../src/views/ApiKeysView.vue'
import TemplatesView from '../src/views/TemplatesView.vue'
import AuditView from '../src/views/AuditView.vue'
import TlsFleetView from '../src/views/TlsFleetView.vue'
import IncidentGroupsView from '../src/views/IncidentGroupsView.vue'

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

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
  await new Promise((r) => setTimeout(r, 0))
}

async function mountView(component) {
  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

  const wrapper = mount(component, {
    global: {
      plugins: [i18n, createPinia(), router],
      stubs: { IncidentPlaybackMap: true, IncidentDiagnosticPanel: true },
    },
  })
  await flush()
  return wrapper
}

describe('EmptyState rollout — views render the real component when empty', () => {
  it.each([
    ['IncidentsView', IncidentsView, en.incidents.no_incidents],
    ['ApiKeysView', ApiKeysView, en.apiKeys.empty_title],
    ['TemplatesView', TemplatesView, en.templates.no_templates],
    ['AuditView', AuditView, en.audit.empty],
    ['TlsFleetView', TlsFleetView, en.tls_fleet.empty],
    ['IncidentGroupsView', IncidentGroupsView, en.incidentGroups.empty],
  ])('%s shows the EmptyState component with the expected title', async (_name, component, expectedTitle) => {
    const wrapper = await mountView(component)
    const title = wrapper.find('.empty-state__title')
    expect(title.exists()).toBe(true)
    expect(title.text()).toBe(expectedTitle)
    // A real EmptyState renders an icon slot (svg) — guards against a plain
    // <p class="empty-state__title"> imitation instead of the component.
    expect(wrapper.find('.empty-state__icon svg').exists()).toBe(true)
    wrapper.unmount()
  })
})
