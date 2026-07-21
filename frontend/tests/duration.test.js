import { describe, it, expect, vi } from 'vitest'

// B3 — trois vues affichaient une durée d'incident avec leur propre helper et
// des formats divergents : le même incident de 90 min se lisait « 1.5h » sur
// la timeline des sondes, « 1h30min » sur la page publique et « 1h 30m » dans
// la liste. Les unités étaient codées en dur, donc jamais traduites.

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key, params) => {
      const map = {
        'common.duration_seconds': `${params?.n}s`,
        'common.duration_minutes': `${params?.n}min`,
        'common.duration_hours': `${params?.n}h`,
        'common.duration_hours_minutes': `${params?.h}h ${params?.m}min`,
      }
      return map[key] ?? key
    },
    locale: { value: 'en' },
  }),
}))

vi.mock('../src/composables/useTimezone', () => ({
  useTimezone: () => ({ format: () => '' }),
}))

const { useDateFormat } = await import('../src/composables/useDateFormat')

describe('formatDuration', () => {
  const { formatDuration } = useDateFormat()

  it.each([
    [0, '0s'],
    [45, '45s'],
    [59, '59s'],
    [60, '1min'],
    [90, '1min'],
    [3599, '59min'],
    [3600, '1h'],
    [5400, '1h 30min'],
    [7200, '2h'],
  ])('renders %ss as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })

  it('renders an em dash rather than a bogus duration when there is none', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(undefined)).toBe('—')
    expect(formatDuration(NaN)).toBe('—')
  })

  it('never renders a negative duration', () => {
    expect(formatDuration(-10)).toBe('0s')
  })
})

describe('formatDurationMinutes', () => {
  const { formatDuration, formatDurationMinutes } = useDateFormat()

  it('agrees with the seconds variant — the public page gets minutes', () => {
    expect(formatDurationMinutes(90)).toBe(formatDuration(90 * 60))
    expect(formatDurationMinutes(90)).toBe('1h 30min')
    expect(formatDurationMinutes(5)).toBe('5min')
  })

  it('handles a missing duration', () => {
    expect(formatDurationMinutes(null)).toBe('—')
  })
})
