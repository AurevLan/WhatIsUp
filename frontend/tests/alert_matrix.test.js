/**
 * Tests for the AlertMatrix card-based UI (Phase 1 refactor).
 * Covers: ChannelChip toggle, AddRuleMenu filtering, ConditionCard state, AlertMatrix load/add/remove flow.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/client', () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ isSuperadmin: false }),
}))

import api from '../src/api/client'
import ChannelChip from '../src/components/monitors/alert-matrix/ChannelChip.vue'
import AddRuleMenu from '../src/components/monitors/alert-matrix/AddRuleMenu.vue'
import ConditionCard from '../src/components/monitors/alert-matrix/ConditionCard.vue'
import TemplatePicker from '../src/components/monitors/alert-matrix/TemplatePicker.vue'
import AlertMatrix from '../src/components/monitors/AlertMatrix.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

function makeChannel(overrides = {}) {
  return { id: 'ch-1', name: 'Slack #ops', type: 'slack', ...overrides }
}

// Stub ScheduleEditor, router-link and BaseModal — not under test here
const globalStubs = {
  ScheduleEditor: { template: '<div class="schedule-stub" />' },
  'router-link': { template: '<a><slot /></a>' },
  BaseModal: {
    props: ['modelValue', 'title', 'size'],
    template: '<div v-if="modelValue" class="modal-stub"><slot /><div class="footer-stub"><slot name="footer" /></div></div>',
  },
}

describe('ChannelChip', () => {
  it('emits toggle on click', async () => {
    const wrapper = mount(ChannelChip, {
      props: { channel: makeChannel(), active: false },
      global: { plugins: [i18n] },
    })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })

  it('shows remove marker when active+removable', () => {
    const wrapper = mount(ChannelChip, {
      props: { channel: makeChannel(), active: true, removable: true },
      global: { plugins: [i18n] },
    })
    expect(wrapper.text()).toContain('✕')
  })
})

describe('AddRuleMenu', () => {
  function mountMenu(props) {
    return mount(AddRuleMenu, {
      props,
      global: { plugins: [i18n], stubs: globalStubs },
    })
  }

  function conditionButtons(wrapper) {
    return wrapper.findAll('.modal-stub button').filter(b => /font-mono/.test(b.html()))
  }

  it('filters out already-used conditions', async () => {
    const wrapper = mountMenu({
      available: ['any_down', 'all_down', 'ssl_expiry'],
      used: ['any_down'],
    })
    await wrapper.find('button').trigger('click')
    const texts = conditionButtons(wrapper).map(b => b.text())
    expect(texts.some(t => t.includes('all_down'))).toBe(true)
    expect(texts.some(t => t.includes('ssl_expiry'))).toBe(true)
    expect(texts.some(t => t.includes('any_down'))).toBe(false)
  })

  it('disables trigger when nothing available', () => {
    const wrapper = mountMenu({ available: ['any_down'], used: ['any_down'] })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
  })

  it('emits add once per selected condition on confirm', async () => {
    const wrapper = mountMenu({ available: ['any_down', 'all_down', 'ssl_expiry'], used: [] })
    await wrapper.find('button').trigger('click')
    const options = conditionButtons(wrapper)
    await options[0].trigger('click')
    await options[2].trigger('click')
    const confirmBtn = wrapper.findAll('.footer-stub button').filter(b => b.text().startsWith('Add'))[0]
    await confirmBtn.trigger('click')
    expect(wrapper.emitted('add')).toEqual([['any_down'], ['ssl_expiry']])
  })

  it('select all toggles every option', async () => {
    const wrapper = mountMenu({ available: ['any_down', 'all_down'], used: [] })
    await wrapper.find('button').trigger('click')
    const selectAllBtn = wrapper.findAll('.footer-stub button').filter(b => b.text() === 'Select all')[0]
    await selectAllBtn.trigger('click')
    const wrappers = conditionButtons(wrapper).map(b => b.element.closest('.rounded-lg'))
    expect(wrappers.every(el => el.className.includes('border-blue-500'))).toBe(true)
  })
})

describe('ConditionCard', () => {
  function makeRow(overrides = {}) {
    return {
      condition: 'any_down',
      channel_ids: [],
      enabled: true,
      min_duration_seconds: 0,
      renotify_after_minutes: null,
      threshold_value: null,
      digest_minutes: 0,
      schedule: null,
      ...overrides,
    }
  }

  it('toggles channel id in row.channel_ids on chip click', async () => {
    const row = makeRow()
    const ch = makeChannel()
    const wrapper = mount(ConditionCard, {
      props: { row, channels: [ch] },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await wrapper.findComponent(ChannelChip).find('button').trigger('click')
    expect(row.channel_ids).toEqual(['ch-1'])
    await wrapper.findComponent(ChannelChip).find('button').trigger('click')
    expect(row.channel_ids).toEqual([])
  })

  it('emits remove when ✕ clicked', async () => {
    const wrapper = mount(ConditionCard, {
      props: { row: makeRow(), channels: [] },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    // The first ✕ button in header
    const buttons = wrapper.findAll('button').filter(b => b.text() === '✕')
    await buttons[0].trigger('click')
    expect(wrapper.emitted('remove')).toHaveLength(1)
  })
})

describe('TemplatePicker', () => {
  beforeEach(() => {
    api.get.mockReset()
  })

  it('loads templates on open and emits apply with selected rows', async () => {
    api.get.mockResolvedValue({
      data: [
        { id: 'standard', rows: [{ condition: 'any_down' }, { condition: 'ssl_expiry' }] },
        { id: 'strict', rows: [{ condition: 'all_down' }] },
      ],
    })
    const wrapper = mount(TemplatePicker, {
      props: { checkType: 'http', hasExistingRows: false },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(api.get).toHaveBeenCalledWith('/alerts/matrix-templates/http')
    // Pick the first template card
    const cards = wrapper.findAll('.modal-stub button').filter(b => /font-semibold/.test(b.html()))
    await cards[0].trigger('click')
    const applyBtn = wrapper.findAll('.footer-stub button').filter(b => b.text() === 'Apply')[0]
    await applyBtn.trigger('click')
    expect(wrapper.emitted('apply')).toHaveLength(1)
    expect(wrapper.emitted('apply')[0][0]).toEqual([{ condition: 'any_down' }, { condition: 'ssl_expiry' }])
  })

  it('shows replace warning when hasExistingRows is true and a template is selected', async () => {
    api.get.mockResolvedValue({
      data: [{ id: 'standard', rows: [{ condition: 'any_down' }] }],
    })
    const wrapper = mount(TemplatePicker, {
      props: { checkType: 'http', hasExistingRows: true },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await wrapper.find('button').trigger('click')
    await flushPromises()
    const cards = wrapper.findAll('.modal-stub button').filter(b => /font-semibold/.test(b.html()))
    await cards[0].trigger('click')
    expect(wrapper.text()).toContain(en.alert_matrix.templates.warn_replace)
  })
})

describe('AlertMatrix integration', () => {
  beforeEach(() => {
    api.get.mockReset()
    api.put.mockReset()
    api.post.mockReset()
    api.post.mockResolvedValue({ data: { window_days: 30, counts: [], total: 0 } })
  })

  it('loads and renders one card per returned row', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: [makeChannel()] })
      return Promise.resolve({
        data: {
          monitor_id: 'mon-1',
          rows: [
            {
              condition: 'any_down',
              channels: [makeChannel()],
              enabled: true,
              min_duration_seconds: 0,
              digest_minutes: 0,
            },
          ],
        },
      })
    })
    const wrapper = mount(AlertMatrix, {
      props: { monitorId: 'mon-1', checkType: 'http' },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    expect(wrapper.findAllComponents(ConditionCard)).toHaveLength(1)
  })

  it('shows empty hint when no rows', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: [makeChannel()] })
      return Promise.resolve({ data: { monitor_id: 'mon-1', rows: [] } })
    })
    const wrapper = mount(AlertMatrix, {
      props: { monitorId: 'mon-1', checkType: 'http' },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    expect(wrapper.text()).toContain(en.alert_matrix.empty_hint)
  })

  it('adds a new row via AddRuleMenu', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: [makeChannel()] })
      return Promise.resolve({ data: { monitor_id: 'mon-1', rows: [] } })
    })
    const wrapper = mount(AlertMatrix, {
      props: { monitorId: 'mon-1', checkType: 'http' },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    const menu = wrapper.findComponent(AddRuleMenu)
    menu.vm.$emit('add', 'any_down')
    await flushPromises()
    expect(wrapper.findAllComponents(ConditionCard)).toHaveLength(1)
  })

  it('forwards preview counts to ConditionCards as impactCount', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    api.get.mockImplementation((url) => {
      if (url === '/alerts/channels') return Promise.resolve({ data: [makeChannel()] })
      return Promise.resolve({
        data: {
          monitor_id: 'mon-1',
          rows: [
            {
              condition: 'any_down',
              channels: [makeChannel()],
              enabled: true,
              min_duration_seconds: 0,
              digest_minutes: 0,
            },
          ],
        },
      })
    })
    api.post.mockResolvedValue({
      data: { window_days: 30, counts: [{ condition: 'any_down', count: 7 }], total: 7 },
    })
    const wrapper = mount(AlertMatrix, {
      props: { monitorId: 'mon-1', checkType: 'http' },
      global: { plugins: [i18n], stubs: globalStubs },
    })
    await flushPromises()
    vi.advanceTimersByTime(600)
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith(
      '/alerts/monitors/mon-1/matrix/preview',
      expect.any(Object)
    )
    const card = wrapper.findComponent(ConditionCard)
    expect(card.props('impactCount')).toBe(7)
    expect(wrapper.text()).toContain('≈ 7 / 30j')
    vi.useRealTimers()
  })
})
