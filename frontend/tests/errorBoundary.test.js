import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k, locale: { value: 'en-US' } }),
}))

import ErrorBoundary from '../src/components/shared/ErrorBoundary.vue'

const Throwing = defineComponent({
  props: { trigger: { type: Boolean, default: false } },
  setup(props) {
    return () => {
      if (props.trigger) throw new Error('boom from child')
      return h('div', { class: 'child-ok' }, 'child rendered')
    }
  },
})

beforeEach(() => {
  // silence the expected console.error from onErrorCaptured
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('ErrorBoundary', () => {
  it('renders the slot content when no error', () => {
    const w = mount(ErrorBoundary, {
      slots: { default: () => h(Throwing, { trigger: false }) },
    })
    expect(w.find('.child-ok').exists()).toBe(true)
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })

  it('captures a child error and renders fallback UI', async () => {
    const w = mount(ErrorBoundary, {
      slots: { default: () => h(Throwing, { trigger: true }) },
    })
    await flushPromises()
    const alert = w.find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('error_boundary.title')
    expect(alert.text()).toContain('error_boundary.reload')
  })

  it('shows error stack inside the details block', async () => {
    const w = mount(ErrorBoundary, {
      slots: { default: () => h(Throwing, { trigger: true }) },
    })
    await flushPromises()
    expect(w.find('details').exists()).toBe(true)
    expect(w.find('pre').text()).toContain('boom from child')
  })

  it('reset button hides fallback and re-renders the slot', async () => {
    const Wrapper = defineComponent({
      data: () => ({ trigger: true }),
      methods: { stop() { this.trigger = false } },
      render() {
        return h(ErrorBoundary, null, {
          default: () => h(Throwing, { trigger: this.trigger }),
        })
      },
    })
    const w = mount(Wrapper)
    await flushPromises()
    expect(w.find('[role="alert"]').exists()).toBe(true)

    // stop throwing then click "Dismiss"
    w.vm.stop()
    await w.findAll('button').at(1).trigger('click')
    await flushPromises()

    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.find('.child-ok').exists()).toBe(true)
  })
})
