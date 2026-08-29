import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import EnabledBadge from '../src/components/shared/EnabledBadge.vue'

describe('EnabledBadge', () => {
  it('renders the up/badge class and given label when enabled', () => {
    const w = mount(EnabledBadge, { props: { enabled: true, label: 'Enabled' } })
    expect(w.classes()).toContain('badge')
    expect(w.classes()).toContain('badge-up')
    expect(w.text()).toBe('Enabled')
  })

  it('renders the unknown/badge class and given label when disabled', () => {
    const w = mount(EnabledBadge, { props: { enabled: false, label: 'Disabled' } })
    expect(w.classes()).toContain('badge')
    expect(w.classes()).toContain('badge-unknown')
    expect(w.text()).toBe('Disabled')
  })

  it('lets a slot override the label, for a caller with grammatically-agreed wording', () => {
    const w = mount(EnabledBadge, {
      props: { enabled: false },
      slots: { default: 'désactivée' },
    })
    expect(w.text()).toBe('désactivée')
  })
})
