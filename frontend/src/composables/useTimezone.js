// Timezone resolution + date formatting helpers (T1-13).
//
// Source of truth: the authenticated user's `timezone` preference if set,
// otherwise the browser's resolved IANA zone. Timestamps in the DB are UTC;
// this layer handles display-time conversion only.

import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

/**
 * @returns {{
 *   timezone: import('vue').ComputedRef<string>,
 *   isUserPref: import('vue').ComputedRef<boolean>,
 *   format: (iso: string|Date, opts?: Intl.DateTimeFormatOptions, locale?: string) => string,
 *   formatRelative: (iso: string|Date, locale?: string) => string,
 *   formatAbsolute: (iso: string|Date, locale?: string) => string,
 * }}
 */
export function useTimezone() {
  const auth = useAuthStore()

  const timezone = computed(() => auth.user?.timezone || browserTimezone())
  const isUserPref = computed(() => !!auth.user?.timezone)

  const toDate = (v) => (v instanceof Date ? v : new Date(v))

  const format = (v, opts = {}, locale) => {
    if (v == null) return ''
    const date = toDate(v)
    if (Number.isNaN(date.getTime())) return ''
    return new Intl.DateTimeFormat(locale, { timeZone: timezone.value, ...opts }).format(date)
  }

  const formatAbsolute = (v, locale) =>
    format(
      v,
      {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short',
      },
      locale,
    )

  const formatRelative = (v, locale) => {
    if (v == null) return ''
    const date = toDate(v)
    if (Number.isNaN(date.getTime())) return ''
    const diff = (date.getTime() - Date.now()) / 1000
    const abs = Math.abs(diff)
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
    // Pick the coarsest unit that yields a magnitude ≥ 1.
    const [unit, factor] =
      abs < 60
        ? ['second', 1]
        : abs < 3600
          ? ['minute', 60]
          : abs < 86400
            ? ['hour', 3600]
            : abs < 2592000
              ? ['day', 86400]
              : abs < 31536000
                ? ['month', 2592000]
                : ['year', 31536000]
    return rtf.format(Math.round(diff / factor), unit)
  }

  return { timezone, isUserPref, format, formatRelative, formatAbsolute }
}
