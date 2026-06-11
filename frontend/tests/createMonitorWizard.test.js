/**
 * CreateMonitorWizard — step 1 type cards.
 * Native types stay in the wizard flow; advanced types hand over to the
 * advanced form via switch-advanced(type).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
  },
}))

vi.mock('../src/stores/monitors', () => ({
  useMonitorStore: () => ({ create: vi.fn() }),
}))

import CreateMonitorWizard from '../src/components/monitors/CreateMonitorWizard.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const globalConfig = {
  plugins: [i18n],
  stubs: {
    BaseModal: {
      props: ['title', 'size'],
      template: '<div class="modal-stub"><slot /><div class="footer-stub"><slot name="footer" /></div></div>',
    },
  },
}

function cardByLabel(wrapper, label) {
  return wrapper
    .findAll('.wizard__type-card')
    .find((c) => c.find('.text-sm.font-semibold').text() === label)
}

describe('CreateMonitorWizard — type cards', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders all 12 check types', () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    expect(w.findAll('.wizard__type-card')).toHaveLength(12)
  })

  it('selects a native type locally without emitting switch-advanced', async () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    const httpCard = cardByLabel(w, 'HTTP')
    await httpCard.trigger('click')
    expect(w.emitted('switch-advanced')).toBeUndefined()
    expect(httpCard.classes()).toContain('wizard__type-card--selected')
  })

  it('emits switch-advanced with the chosen type for an advanced card', async () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    const scenarioCard = cardByLabel(w, 'Scenario')
    await scenarioCard.trigger('click')
    expect(w.emitted('switch-advanced')).toEqual([['scenario']])
    // The wizard form must not adopt the advanced type.
    expect(scenarioCard.classes()).not.toContain('wizard__type-card--selected')
  })

  it('emits switch-advanced with each advanced type value', async () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    const expectations = [
      ['Keyword', 'keyword'],
      ['JSON', 'json_path'],
      ['Ping', 'ping'],
      ['UDP', 'udp'],
      ['SMTP', 'smtp'],
      ['Domain', 'domain_expiry'],
      ['Composite', 'composite'],
    ]
    for (const [label, value] of expectations) {
      await cardByLabel(w, label).trigger('click')
      const emitted = w.emitted('switch-advanced')
      expect(emitted[emitted.length - 1]).toEqual([value])
    }
  })

  it('marks advanced cards with the opens-advanced hint', () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    const scenarioCard = cardByLabel(w, 'Scenario')
    expect(scenarioCard.classes()).toContain('wizard__type-card--advanced')
    expect(scenarioCard.find('.wizard__type-card-advanced-hint').text()).toContain(
      en.wizard.opens_advanced,
    )
    const httpCard = cardByLabel(w, 'HTTP')
    expect(httpCard.classes()).not.toContain('wizard__type-card--advanced')
    expect(httpCard.find('.wizard__type-card-advanced-hint').exists()).toBe(false)
  })

  it('keeps the explicit advanced-form link (no payload)', async () => {
    const w = mount(CreateMonitorWizard, { global: globalConfig })
    const link = w
      .findAll('button')
      .find((b) => b.text() === en.wizard.advanced_link)
    await link.trigger('click')
    expect(w.emitted('switch-advanced')).toEqual([[]])
  })
})
