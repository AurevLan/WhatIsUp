import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBadge from '../src/components/shared/StatusBadge.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k }),
}))

function render(props) {
  return mount(StatusBadge, { props })
}

describe('StatusBadge', () => {
  it.each([
    ['up', 'badge-up', 'status.up'],
    ['down', 'badge-down', 'status.down'],
    ['timeout', 'badge-timeout', 'status.timeout'],
    ['error', 'badge-error', 'status.error'],
    ['paused', 'badge-unknown', 'status.paused'],
  ])('renders %s with the right badge class and i18n label', (status, cls, key) => {
    const w = render({ status })
    expect(w.classes()).toContain(cls)
    expect(w.text()).toBe(key)
  })

  it('falls back to no_data for unknown / null status', () => {
    expect(render({ status: 'wat' }).text()).toBe('status.no_data')
    expect(render({ status: 'wat' }).classes()).toContain('badge-unknown')
    expect(render({ status: null }).text()).toBe('status.no_data')
  })

  it('shows a dot by default and hides it when dot=false', () => {
    expect(render({ status: 'up' }).find('.status-badge__dot').exists()).toBe(true)
    expect(render({ status: 'up', dot: false }).find('.status-badge__dot').exists()).toBe(false)
  })
})
