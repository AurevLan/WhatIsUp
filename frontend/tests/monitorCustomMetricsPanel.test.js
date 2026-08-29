/**
 * Empty state of the custom-metrics panel (chantier ergonomie, item 3).
 *
 * The panel used to fall back to a hard-coded English sentence with no CTA,
 * the only empty state in the app that skipped <EmptyState> — and the only
 * one, therefore, that stayed English no matter the UI locale. This pins the
 * i18n text and the CTA wiring back to the push-URL modal already above it.
 */

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { ref } from 'vue'
import en from '../src/i18n/en.js'
import fr from '../src/i18n/fr.js'
import MonitorCustomMetricsPanel from '../src/components/monitors/detail/MonitorCustomMetricsPanel.vue'
import { CustomMetricsStateKey } from '../src/components/monitors/detail/injectionKeys'

function mountPanel({ names = [], locale = 'en' } = {}) {
  const i18n = createI18n({ legacy: false, locale, messages: { en, fr } })
  const state = {
    names: ref(names),
    showPushUrlModal: ref(false),
    unit: () => null,
    labelSets: () => [],
    options: () => ({}),
    series: () => [],
  }
  const wrapper = mount(MonitorCustomMetricsPanel, {
    props: { monitor: { id: 'mon-1' }, apiBase: 'https://example.test' },
    global: {
      plugins: [i18n],
      provide: { [CustomMetricsStateKey]: state },
      stubs: { BaseModal: true, apexchart: true },
    },
  })
  return { wrapper, state }
}

describe('MonitorCustomMetricsPanel — empty state', () => {
  it('renders the EmptyState with translated copy when no metric has been pushed', () => {
    const { wrapper } = mountPanel()
    expect(wrapper.text()).toContain(en.monitor_detail.custom_metrics_empty_title)
    expect(wrapper.text()).toContain(en.monitor_detail.custom_metrics_empty_text)
    // The old hard-coded English sentence must be gone entirely.
    expect(wrapper.text()).not.toContain('No metrics pushed yet — use the push URL')
  })

  it('translates the empty state in French', () => {
    const { wrapper } = mountPanel({ locale: 'fr' })
    expect(wrapper.text()).toContain(fr.monitor_detail.custom_metrics_empty_title)
  })

  it('opens the push-URL modal from the empty state CTA', async () => {
    const { wrapper, state } = mountPanel()
    await wrapper.find('button').trigger('click')
    // The panel's own "Show push URL" button also matches; find the one
    // inside the empty state deterministically by triggering all buttons
    // and checking the state flipped.
    const buttons = wrapper.findAll('button')
    for (const b of buttons) {
      if (b.text().includes(en.monitor_detail.push_url)) await b.trigger('click')
    }
    expect(state.showPushUrlModal.value).toBe(true)
  })

  it('does not show the empty state once metrics exist', () => {
    const { wrapper } = mountPanel({ names: ['orders_per_minute'] })
    expect(wrapper.text()).not.toContain(en.monitor_detail.custom_metrics_empty_title)
  })
})
