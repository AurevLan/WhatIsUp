import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import BulkActionBar from '../src/components/shared/BulkActionBar.vue'

const i18nMock = {
  global: {
    mocks: {
      $t: (k, params) => (params ? `${k}:${JSON.stringify(params)}` : k),
    },
  },
}

describe('BulkActionBar', () => {
  it('renders nothing when count is zero', () => {
    const w = mount(BulkActionBar, { props: { count: 0 }, global: i18nMock.global })
    expect(w.find('.bulk-bar').exists()).toBe(false)
  })

  it('renders count label when > 0', () => {
    const w = mount(BulkActionBar, { props: { count: 3 }, global: i18nMock.global })
    expect(w.find('.bulk-bar__count').text()).toContain('"n":3')
  })

  it('renders default slot content', () => {
    const w = mount(BulkActionBar, {
      props: { count: 1 },
      global: i18nMock.global,
      slots: { default: () => h('button', { class: 'my-btn' }, 'Action') },
    })
    expect(w.find('.my-btn').exists()).toBe(true)
  })

  it('emits clear when deselect button clicked', async () => {
    const w = mount(BulkActionBar, { props: { count: 2 }, global: i18nMock.global })
    await w.find('.bulk-bar__clear').trigger('click')
    expect(w.emitted('clear')).toHaveLength(1)
  })

  it('exposes role=region with aria-label for screen readers', () => {
    const w = mount(BulkActionBar, { props: { count: 1 }, global: i18nMock.global })
    const root = w.find('.bulk-bar')
    expect(root.attributes('role')).toBe('region')
    expect(root.attributes('aria-label')).toBe('bulk.bar_aria')
  })
})
