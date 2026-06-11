// Locale-aware date formatting helpers shared across views.
//
// Wraps useTimezone() (user timezone preference, T1-13) with the current
// vue-i18n locale so every view renders dates the same way. Relative strings
// are translated through i18n (common.relative_* keys in en.js / fr.js).

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTimezone } from './useTimezone'

const INTL_LOCALES = { en: 'en-US', fr: 'fr-FR' }

const DEFAULT_DATETIME_OPTS = {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
}

export function useDateFormat() {
  const { t, locale } = useI18n()
  const { format: tzFormat } = useTimezone()

  const intlLocale = computed(() => INTL_LOCALES[locale.value] || locale.value)

  /**
   * Full date + time by default ("15/06/2026 12:00:00" in fr).
   * Pass Intl.DateTimeFormat options to customize the rendering
   * (e.g. `{ dateStyle: 'medium' }` or `{ month: 'short', day: 'numeric' }`).
   */
  function formatDate(dt, opts = DEFAULT_DATETIME_OPTS) {
    if (!dt) return '—'
    return tzFormat(dt, opts, intlLocale.value) || '—'
  }

  /** Date only — "15/06/2026" (fr) / "06/15/2026" (en). */
  function formatDateShort(dt) {
    return formatDate(dt, { day: '2-digit', month: '2-digit', year: 'numeric' })
  }

  /**
   * "il y a 5min" / "5min ago". Minute granularity by default;
   * `{ withSeconds: true }` renders "12s ago" under one minute
   * instead of "just now".
   */
  function formatRelative(dt, { withSeconds = false } = {}) {
    if (!dt) return '—'
    const time = new Date(dt).getTime()
    if (Number.isNaN(time)) return '—'
    const secs = Math.max(0, Math.floor((Date.now() - time) / 1000))
    if (secs < 60) {
      return withSeconds
        ? t('common.relative_seconds_ago', { n: secs })
        : t('common.relative_just_now')
    }
    const mins = Math.floor(secs / 60)
    if (mins < 60) return t('common.relative_minutes_ago', { n: mins })
    const hours = Math.floor(mins / 60)
    if (hours < 24) return t('common.relative_hours_ago', { n: hours })
    return t('common.relative_days_ago', { n: Math.floor(hours / 24) })
  }

  return { intlLocale, formatDate, formatDateShort, formatRelative }
}
