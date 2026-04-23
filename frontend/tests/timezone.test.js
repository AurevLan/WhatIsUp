import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { useTimezone } from '../src/composables/useTimezone'
import FormattedDate from '../src/components/shared/FormattedDate.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ locale: { value: 'en-US' } }),
}))

// Minimal stub that matches the shape useTimezone reads.
let mockUser = null
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    user: mockUser,
  }),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  mockUser = null
})

describe('useTimezone', () => {
  it('falls back to browser timezone when user has no preference', () => {
    const { timezone, isUserPref } = useTimezone()
    expect(typeof timezone.value).toBe('string')
    expect(timezone.value.length).toBeGreaterThan(0)
    expect(isUserPref.value).toBe(false)
  })

  it('uses user preference when set', () => {
    mockUser = { timezone: 'Asia/Tokyo' }
    const { timezone, isUserPref } = useTimezone()
    expect(timezone.value).toBe('Asia/Tokyo')
    expect(isUserPref.value).toBe(true)
  })

  it('format returns a locale-aware string in the selected zone', () => {
    mockUser = { timezone: 'Europe/Paris' }
    const { format } = useTimezone()
    const s = format('2026-06-15T10:00:00Z', { hour: '2-digit', minute: '2-digit', hour12: false })
    // 10:00 UTC in June → 12:00 Paris (CEST, UTC+2)
    expect(s).toContain('12:00')
  })

  it('format returns empty string on invalid input', () => {
    const { format } = useTimezone()
    expect(format(null)).toBe('')
    expect(format('not-a-date')).toBe('')
  })

  it('formatRelative picks a reasonable unit', () => {
    const { formatRelative } = useTimezone()
    const past = new Date(Date.now() - 3600_000) // 1h ago
    const rel = formatRelative(past)
    expect(rel).toMatch(/hour|hr/)
  })
})

describe('FormattedDate.vue', () => {
  it('renders nothing (em dash) for null value', () => {
    const wrapper = mount(FormattedDate, { props: { value: null } })
    expect(wrapper.text()).toBe('—')
  })

  it('renders a <time> element with datetime + title attributes', () => {
    mockUser = { timezone: 'UTC' }
    const wrapper = mount(FormattedDate, {
      props: { value: '2026-04-23T12:00:00Z', format: 'datetime' },
    })
    const time = wrapper.find('time')
    expect(time.exists()).toBe(true)
    expect(time.attributes('datetime')).toBe('2026-04-23T12:00:00.000Z')
    expect(time.attributes('title')).toMatch(/UTC/)
  })

  it('format="relative" yields a relative string', () => {
    mockUser = { timezone: 'UTC' }
    const past = new Date(Date.now() - 120_000).toISOString()
    const wrapper = mount(FormattedDate, { props: { value: past, format: 'relative' } })
    expect(wrapper.text()).toMatch(/ago|min/i)
  })
})
