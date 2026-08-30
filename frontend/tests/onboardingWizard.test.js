/**
 * OnboardingWizard — truthful email coverage (plan_cap_v2.md, étape 2).
 *
 * The regression this guards against: the nominal install flow used to
 * create an email alert channel without ever testing it, then show
 * "✓ Email alerts configured / You're all set" regardless. That is
 * forbidden forever — see the "never claims" test below.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}))

vi.mock('../src/stores/monitors', () => ({
  useMonitorStore: () => ({ fetchAll: vi.fn() }),
}))

vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ user: { full_name: '', email: 'user@example.com' } }),
}))

import api from '../src/api/client'
import OnboardingWizard from '../src/components/onboarding/OnboardingWizard.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const globalConfig = {
  plugins: [i18n],
  stubs: { 'router-link': { template: '<a><slot /></a>' } },
}

function mountWizard() {
  return mount(OnboardingWizard, { global: globalConfig })
}

function clickByText(wrapper, selector, text) {
  const btn = wrapper.findAll(selector).find((b) => b.text().includes(text))
  if (!btn) throw new Error(`No "${selector}" with text "${text}"`)
  return btn.trigger('click')
}

// Advance from step 1 to step 3 without creating a monitor, so tests that
// only care about the alert step don't also need to mock the monitor
// creation/auto-rule calls.
async function goToAlertStep(wrapper) {
  await clickByText(wrapper, '.btn-primary', en.onboarding.next) // step 1 -> 2
  await wrapper.find('.onboarding__skip-link').trigger('click') // step 2 -> 3 (skip)
}

describe('OnboardingWizard — email coverage honesty', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.post.mockReset()
    api.patch.mockReset()
  })

  it('never displays a message claiming email alerts are active when SMTP is not configured', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/onboarding/status') return Promise.resolve({ data: { email_available: false } })
      return Promise.resolve({ data: [] })
    })
    api.post.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: { id: 'ch-1' } })
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountWizard()
    await flushPromises() // onMounted status fetch resolves

    await goToAlertStep(wrapper)
    // The warning is shown as soon as the step renders, before the user
    // acts on the email field at all.
    expect(wrapper.text()).toContain(en.onboarding.smtp_unavailable_notice)

    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await clickByText(wrapper, '.btn-primary', en.onboarding.create_alert)
    await flushPromises()

    // Already known to be unavailable server-side — no point spending a
    // round trip to confirm what /onboarding/status already said.
    expect(api.post).not.toHaveBeenCalledWith('/alerts/channels/ch-1/test')

    const text = wrapper.text()
    expect(text).not.toContain(en.onboarding.alert_created)
    expect(text).toContain('Email alerts are not active')
    expect(text).toContain('the server has no SMTP host configured')
  })

  it('shows a verified success message when the channel test succeeds', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/onboarding/status') return Promise.resolve({ data: { email_available: true } })
      return Promise.resolve({ data: [] })
    })
    api.post.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: { id: 'ch-1' } })
      if (url === '/alerts/channels/ch-1/test') {
        return Promise.resolve({ data: { success: true, detail: 'Email envoyé à : user@example.com' } })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountWizard()
    await flushPromises()
    await goToAlertStep(wrapper)
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await clickByText(wrapper, '.btn-primary', en.onboarding.create_alert)
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith('/alerts/channels/ch-1/test')
    expect(wrapper.text()).toContain(en.onboarding.alert_created)
  })

  it('reports the real test failure reason when SMTP is configured but delivery fails', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/onboarding/status') return Promise.resolve({ data: { email_available: true } })
      return Promise.resolve({ data: [] })
    })
    api.post.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: { id: 'ch-1' } })
      if (url === '/alerts/channels/ch-1/test') {
        return Promise.resolve({ data: { success: false, detail: 'Connection refused' } })
      }
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountWizard()
    await flushPromises()
    await goToAlertStep(wrapper)
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await clickByText(wrapper, '.btn-primary', en.onboarding.create_alert)
    await flushPromises()

    const text = wrapper.text()
    expect(text).not.toContain(en.onboarding.alert_created)
    expect(text).toContain('Connection refused')
  })

  it('shows a visible error and stays on the step when monitor creation fails', async () => {
    api.get.mockResolvedValue({ data: { email_available: true } })
    api.post.mockImplementation((url) => {
      if (url === '/monitors') return Promise.reject({ response: { data: { detail: 'boom' } } })
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountWizard()
    await flushPromises()
    await clickByText(wrapper, '.btn-primary', en.onboarding.next) // step 1 -> 2

    await wrapper.find('input[type="text"]').setValue('https://example.com')
    await clickByText(wrapper, '.btn-primary', en.onboarding.create_monitor)
    await flushPromises()

    expect(wrapper.text()).toContain('boom')
    // Did not silently advance to step 3.
    expect(wrapper.find('input[type="email"]').exists()).toBe(false)
  })

  it('shows a visible error and stays on the step when alert channel creation fails', async () => {
    api.get.mockResolvedValue({ data: { email_available: true } })
    api.post.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.reject({ response: { data: { detail: 'nope' } } })
      return Promise.resolve({ data: {} })
    })

    const wrapper = mountWizard()
    await flushPromises()
    await goToAlertStep(wrapper)
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await clickByText(wrapper, '.btn-primary', en.onboarding.create_alert)
    await flushPromises()

    expect(wrapper.text()).toContain('nope')
    // Did not silently advance to the done screen.
    expect(wrapper.text()).not.toContain(en.onboarding.done_title)
  })
})
