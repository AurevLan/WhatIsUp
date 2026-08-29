/**
 * On-call configuration UI (plan V2, B-4).
 *
 * The engine has been walking ladders since B-1/B-2; this page is what makes it
 * reachable. Two things are pinned harder than the rest, because both are ways
 * an operator ends up believing they are covered when they are not:
 *
 * - a rotation that designates nobody must say so, not render an empty cell;
 * - a policy with no rungs must say it falls back, not look like a ladder.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import en from '../src/i18n/en.js'

vi.mock('../src/api/oncall', () => ({
  oncallApi: {
    onCallNow: vi.fn(),
    schedules: { list: vi.fn(), remove: vi.fn() },
    policies: { list: vi.fn(), remove: vi.fn() },
  },
}))
vi.mock('../src/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))
const confirmMock = vi.fn().mockResolvedValue(true)
vi.mock('../src/composables/useConfirm', () => ({
  useConfirm: () => ({ confirm: confirmMock }),
}))

import { oncallApi } from '../src/api/oncall'
import OnCallView from '../src/views/OnCallView.vue'

const i18n = createI18n({ legacy: false, locale: 'en', messages: { en } })

const stubs = {
  EmptyState: { props: ['title', 'text'], template: '<div class="empty">{{ title }}</div>' },
  SkeletonRow: true,
  OnCallScheduleModal: true,
  EscalationPolicyModal: true,
}

async function render({ schedules = [], policies = [], now = [] } = {}) {
  oncallApi.schedules.list.mockResolvedValue({ data: schedules })
  oncallApi.policies.list.mockResolvedValue({ data: policies })
  oncallApi.onCallNow.mockResolvedValue({ data: now })
  const w = mount(OnCallView, { global: { plugins: [i18n], stubs } })
  await flushPromises()
  return w
}

function schedule(overrides = {}) {
  return {
    id: 's-1',
    name: 'Prod rota',
    timezone: 'Europe/Paris',
    rotation_type: 'weekly',
    rotation_length_days: 7,
    handoff_time: '09:00',
    enabled: true,
    participants: [{ user_id: 'u-1', position: 0 }],
    ...overrides,
  }
}

describe('OnCallView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.mockResolvedValue(true)
  })

  it('names who is on call right now', async () => {
    const w = await render({
      schedules: [schedule()],
      now: [{ schedule_id: 's-1', schedule_name: 'Prod rota', user_id: 'u-1', username: 'alice' }],
    })
    expect(w.text()).toContain('alice')
  })

  it('says nobody is on call rather than showing an empty cell', async () => {
    // The failure this whole feature exists to remove: an uncovered rotation
    // that reads like a covered one.
    const w = await render({
      schedules: [schedule({ participants: [] })],
      now: [{ schedule_id: 's-1', schedule_name: 'Prod rota', user_id: null }],
    })
    expect(w.text()).toContain(en.oncall.nobody)
  })

  it('flags when an override is what put someone on duty', async () => {
    const w = await render({
      now: [
        {
          schedule_id: 's-1',
          schedule_name: 'Prod rota',
          user_id: 'u-2',
          username: 'bob',
          via_override: true,
        },
      ],
    })
    expect(w.text()).toContain(en.oncall.via_override)
  })

  it('describes a rotation in words, not enum values', async () => {
    const w = await render({ schedules: [schedule({ rotation_type: 'custom_days', rotation_length_days: 3 })] })
    expect(w.text()).toContain('Every 3 days')
    expect(w.text()).not.toContain('custom_days')
  })

  it('spells out a ladder in order with its delays', async () => {
    const w = await render({
      schedules: [schedule()],
      policies: [
        {
          id: 'p-1',
          name: 'Paging',
          enabled: true,
          levels: [
            { position: 0, delay_minutes: 0, target_type: 'channel' },
            { position: 1, delay_minutes: 15, target_type: 'schedule', target_schedule_id: 's-1' },
          ],
        },
      ],
    })
    const text = w.text()
    expect(text).toContain('+15min')
    // The rung pointing at a rotation shows the rotation's name, not its id.
    expect(text).toContain('Prod rota')
  })

  it('warns that a policy with no level falls back instead of escalating', async () => {
    const w = await render({
      policies: [{ id: 'p-1', name: 'Empty', enabled: true, levels: [] }],
    })
    expect(w.text()).toContain(en.oncall.no_levels)
  })

  it('names the cascade impact when confirming a rotation delete', async () => {
    // Deleting a rotation cascades any escalation rung that targets it
    // (FK ondelete=CASCADE on escalation_policy_levels.target_schedule_id) —
    // the confirmation must say so, not just repeat the rotation's name.
    const w = await render({ schedules: [schedule()] })
    await w.find('[title="Delete"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: expect.stringContaining('Prod rota'),
        message: en.oncall.delete_schedule_detail,
      }),
    )
    expect(oncallApi.schedules.remove).toHaveBeenCalledWith('s-1')
  })

  it('names the silent-fallback impact when confirming a policy delete', async () => {
    // Deleting a policy sets AlertRule.escalation_policy_id to NULL (FK
    // ondelete=SET NULL) — a rule using it keeps firing but stops escalating,
    // with no other signal. The confirmation must spell that out.
    const w = await render({ policies: [{ id: 'p-1', name: 'Paging', enabled: true, levels: [] }] })
    await w.find('[title="Delete"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: expect.stringContaining('Paging'),
        message: en.oncall.delete_policy_detail,
      }),
    )
    expect(oncallApi.policies.remove).toHaveBeenCalledWith('p-1')
  })

  it('still renders the page when the on-call endpoint fails', async () => {
    oncallApi.schedules.list.mockResolvedValue({ data: [schedule()] })
    oncallApi.policies.list.mockResolvedValue({ data: [] })
    oncallApi.onCallNow.mockRejectedValue(new Error('boom'))
    const w = mount(OnCallView, { global: { plugins: [i18n], stubs } })
    await flushPromises()
    // Configuration stays editable even if the "right now" widget cannot load.
    expect(w.text()).toContain('Prod rota')
  })
})
