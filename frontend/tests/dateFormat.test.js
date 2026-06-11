import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useDateFormat } from '../src/composables/useDateFormat'

// ── Mocks ────────────────────────────────────────────────────────────────────

let mockLocale = 'fr'

const MESSAGES = {
  fr: {
    'common.relative_just_now': "à l'instant",
    'common.relative_seconds_ago': 'il y a {n}s',
    'common.relative_minutes_ago': 'il y a {n}min',
    'common.relative_hours_ago': 'il y a {n}h',
    'common.relative_days_ago': 'il y a {n}j',
  },
  en: {
    'common.relative_just_now': 'just now',
    'common.relative_seconds_ago': '{n}s ago',
    'common.relative_minutes_ago': '{n}min ago',
    'common.relative_hours_ago': '{n}h ago',
    'common.relative_days_ago': '{n}d ago',
  },
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    locale: {
      get value() {
        return mockLocale
      },
    },
    t: (key, params = {}) => {
      const msg = MESSAGES[mockLocale]?.[key] ?? key
      return msg.replace(/\{(\w+)\}/g, (_, k) => params[k])
    },
  }),
}))

// Minimal stub matching the shape useTimezone reads (same as timezone.test.js).
let mockUser = null
vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({
    user: mockUser,
  }),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  mockUser = { timezone: 'Europe/Paris' }
  mockLocale = 'fr'
})

// ── intlLocale ───────────────────────────────────────────────────────────────

describe('useDateFormat — intlLocale', () => {
  it('maps app locale to a full Intl locale', () => {
    expect(useDateFormat().intlLocale.value).toBe('fr-FR')
    mockLocale = 'en'
    expect(useDateFormat().intlLocale.value).toBe('en-US')
  })

  it('passes through unknown locales unchanged', () => {
    mockLocale = 'de'
    expect(useDateFormat().intlLocale.value).toBe('de')
  })
})

// ── formatDate ───────────────────────────────────────────────────────────────

describe('useDateFormat — formatDate', () => {
  it('renders full date + time in the user timezone (fr)', () => {
    const { formatDate } = useDateFormat()
    // 10:00 UTC in June → 12:00 Paris (CEST, UTC+2)
    const s = formatDate('2026-06-15T10:00:00Z')
    expect(s).toContain('15/06/2026')
    expect(s).toContain('12:00:00')
  })

  it('respects the current locale (en)', () => {
    mockLocale = 'en'
    const { formatDate } = useDateFormat()
    const s = formatDate('2026-06-15T10:00:00Z')
    expect(s).toContain('06/15/2026')
  })

  it('accepts custom Intl options', () => {
    const { formatDate } = useDateFormat()
    const s = formatDate('2026-06-15T10:00:00Z', { dateStyle: 'medium' })
    expect(s).toContain('2026')
    expect(s).not.toContain(':') // date-only
  })

  it('returns an em dash for nullish or invalid input', () => {
    const { formatDate } = useDateFormat()
    expect(formatDate(null)).toBe('—')
    expect(formatDate(undefined)).toBe('—')
    expect(formatDate('not-a-date')).toBe('—')
  })
})

// ── formatDateShort ──────────────────────────────────────────────────────────

describe('useDateFormat — formatDateShort', () => {
  it('renders date only, locale-ordered', () => {
    expect(useDateFormat().formatDateShort('2026-06-15T10:00:00Z')).toBe('15/06/2026')
    mockLocale = 'en'
    expect(useDateFormat().formatDateShort('2026-06-15T10:00:00Z')).toBe('06/15/2026')
  })

  it('returns an em dash for nullish input', () => {
    expect(useDateFormat().formatDateShort(null)).toBe('—')
  })
})

// ── formatRelative ───────────────────────────────────────────────────────────

describe('useDateFormat — formatRelative', () => {
  it('renders "just now" under one minute', () => {
    const { formatRelative } = useDateFormat()
    expect(formatRelative(new Date(Date.now() - 10_000))).toBe("à l'instant")
  })

  it('renders seconds when withSeconds is set', () => {
    const { formatRelative } = useDateFormat()
    expect(formatRelative(new Date(Date.now() - 30_000), { withSeconds: true })).toBe('il y a 30s')
  })

  it('renders minutes, hours and days', () => {
    const { formatRelative } = useDateFormat()
    expect(formatRelative(new Date(Date.now() - 5 * 60_000))).toBe('il y a 5min')
    expect(formatRelative(new Date(Date.now() - 3 * 3_600_000))).toBe('il y a 3h')
    expect(formatRelative(new Date(Date.now() - 2 * 86_400_000))).toBe('il y a 2j')
  })

  it('translates through the current locale', () => {
    mockLocale = 'en'
    const { formatRelative } = useDateFormat()
    expect(formatRelative(new Date(Date.now() - 5 * 60_000))).toBe('5min ago')
  })

  it('returns an em dash for nullish or invalid input', () => {
    const { formatRelative } = useDateFormat()
    expect(formatRelative(null)).toBe('—')
    expect(formatRelative('not-a-date')).toBe('—')
  })
})
