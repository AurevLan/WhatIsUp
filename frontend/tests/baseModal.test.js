/**
 * BaseModal accessibility tests: focus trap, aria-labelledby, Escape close,
 * focus restoration to the triggering element.
 */

import { describe, it, expect, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import BaseModal from '../src/components/BaseModal.vue'

let wrapper = null

function mountModal(options = {}) {
  wrapper = mount(BaseModal, {
    attachTo: document.body,
    props: { title: 'Test modal', ...options.props },
    slots: {
      default: '<input class="slot-input" /><button class="slot-btn">Go</button>',
      ...options.slots,
    },
    global: {
      stubs: { teleport: true },
    },
  })
  return wrapper
}

afterEach(() => {
  if (wrapper) {
    wrapper.unmount()
    wrapper = null
  }
  document.body.innerHTML = ''
})

describe('BaseModal — ARIA attributes', () => {
  it('exposes role=dialog with aria-modal and aria-labelledby pointing to the title', async () => {
    mountModal()
    await nextTick()
    const overlay = wrapper.find('[role="dialog"]')
    expect(overlay.exists()).toBe(true)
    expect(overlay.attributes('aria-modal')).toBe('true')
    const labelledby = overlay.attributes('aria-labelledby')
    expect(labelledby).toBeTruthy()
    const h2 = wrapper.find('h2.modal-title')
    expect(h2.attributes('id')).toBe(labelledby)
  })

  it('omits aria-labelledby when no title is provided', async () => {
    mountModal({ props: { title: '' } })
    await nextTick()
    const overlay = wrapper.find('[role="dialog"]')
    expect(overlay.attributes('aria-labelledby')).toBeUndefined()
  })

  it('emits close on Escape', async () => {
    mountModal()
    await nextTick()
    await wrapper.find('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})

describe('BaseModal — focus trap', () => {
  it('focuses the first focusable element on mount', async () => {
    mountModal()
    await nextTick()
    await nextTick()
    // First focusable inside the panel is the header close button.
    const closeBtn = wrapper.find('button[aria-label="Close"]')
    expect(document.activeElement).toBe(closeBtn.element)
  })

  it('Tab on the last focusable cycles back to the first', async () => {
    mountModal()
    await nextTick()
    await nextTick()
    const slotBtn = wrapper.find('.slot-btn')
    slotBtn.element.focus()
    expect(document.activeElement).toBe(slotBtn.element)

    await wrapper.find('[role="dialog"]').trigger('keydown', { key: 'Tab' })
    const closeBtn = wrapper.find('button[aria-label="Close"]')
    expect(document.activeElement).toBe(closeBtn.element)
  })

  it('Shift+Tab on the first focusable cycles to the last', async () => {
    mountModal()
    await nextTick()
    await nextTick()
    const closeBtn = wrapper.find('button[aria-label="Close"]')
    closeBtn.element.focus()

    await wrapper.find('[role="dialog"]').trigger('keydown', { key: 'Tab', shiftKey: true })
    const slotBtn = wrapper.find('.slot-btn')
    expect(document.activeElement).toBe(slotBtn.element)
  })

  it('Tab in the middle of the cycle does not hijack focus', async () => {
    mountModal()
    await nextTick()
    await nextTick()
    const input = wrapper.find('.slot-input')
    input.element.focus()
    await wrapper.find('[role="dialog"]').trigger('keydown', { key: 'Tab' })
    // Browser default tabbing applies — the trap must not move focus itself.
    expect(document.activeElement).toBe(input.element)
  })

  it('restores focus to the previously focused element on unmount', async () => {
    const trigger = document.createElement('button')
    trigger.id = 'outside-trigger'
    document.body.appendChild(trigger)
    trigger.focus()
    expect(document.activeElement).toBe(trigger)

    mountModal()
    await nextTick()
    await nextTick()
    expect(document.activeElement).not.toBe(trigger)

    wrapper.unmount()
    wrapper = null
    expect(document.activeElement).toBe(trigger)
  })
})
