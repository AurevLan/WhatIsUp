/**
 * F6, plan cap v2 6c — the dependency graph folded into IncidentsView too.
 *
 * "What depends on what" is exactly the question an operator asks while an
 * incident is open — this pins the toggle button on a standalone incident
 * row, following the same expand/collapse pattern already used for the
 * diagnostic and correlation panels on that row.
 */

import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn((url) => {
      if (url === '/incidents/') {
        return Promise.resolve({
          data: [
            {
              id: 'inc-1',
              monitor_id: 'mon-1',
              monitor_name: 'shop-front',
              monitor_check_type: 'http',
              started_at: '2026-09-01T00:00:00Z',
              is_resolved: false,
              acked_at: null,
              group_id: null,
            },
          ],
        })
      }
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    patch: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
  },
}))

import IncidentsView from '../src/views/IncidentsView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const stubs = {
  IncidentPlaybackMap: true,
  IncidentDiagnosticPanel: true,
  IncidentMetricCorrelationPanel: true,
  NetworkVerdictBadge: true,
  DependencyGraph: { template: '<div data-testid="dep-graph-stub" />' },
}

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

async function mountView() {
  const router = makeRouter()
  router.push('/')
  await router.isReady()
  const w = mount(IncidentsView, { global: { plugins: [i18n, createPinia(), router], stubs } })
  await flushPromises()
  return w
}

describe('IncidentsView — dependency graph (F6)', () => {
  it('keeps the graph collapsed by default on a standalone incident row', async () => {
    const w = await mountView()
    expect(w.find('[data-testid="dep-graph-stub"]').exists()).toBe(false)
  })

  it('reveals the graph once the toggle button is clicked', async () => {
    const w = await mountView()
    const toggle = w.findAll('button').find((b) => b.attributes('title') === en.graph.title)
    expect(toggle).toBeTruthy()
    await toggle.trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="dep-graph-stub"]').exists()).toBe(true)
  })
})
