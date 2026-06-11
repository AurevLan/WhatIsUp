import { useI18n } from 'vue-i18n'

const statusCfg = {
  up:      { dot: 'bg-emerald-500', badge: 'badge-up',      label: 'Up' },
  down:    { dot: 'bg-red-500',     badge: 'badge-down',    label: 'Down' },
  timeout: { dot: 'bg-amber-500',   badge: 'badge-timeout', label: 'Timeout' },
  error:   { dot: 'bg-orange-500',  badge: 'badge-error',   label: 'Error' },
}

/**
 * Pure row-display helpers for the monitor list (status badge/dot/label,
 * target formatting, uptime / response-time colors).
 */
export function useMonitorDisplay() {
  const { t } = useI18n()

  function dotClass(s)    { return statusCfg[s]?.dot   ?? 'bg-gray-600' }
  function badgeClass(s)  { return statusCfg[s]?.badge  ?? 'badge-unknown' }
  function statusLabel(s) { return statusCfg[s]?.label  ?? t('status.no_data') }

  function formatTarget(monitor) {
    const raw = monitor.url?.replace(/^https?:\/\//, '') || ''
    if (monitor.check_type === 'tcp')  return monitor.tcp_port  ? `${raw}:${monitor.tcp_port}`  : raw
    if (monitor.check_type === 'udp')  return monitor.udp_port  ? `${raw}:${monitor.udp_port}`  : raw
    if (monitor.check_type === 'smtp') return monitor.smtp_port ? `${raw}:${monitor.smtp_port}` : raw
    return raw
  }

  function uptimeColor(u) {
    if (u == null) return 'text-gray-500'
    if (u >= 99)   return 'text-emerald-400'
    if (u >= 90)   return 'text-amber-400'
    return 'text-red-400'
  }

  function responseTimeColor(ms, monitor) {
    if (ms == null) return 'text-gray-600'
    const p95 = monitor?._p95ResponseTimeMs
    if (p95 != null && p95 > 0) {
      const ratio = ms / p95
      if (ratio <= 0.6)  return 'text-emerald-400'
      if (ratio <= 1.2)  return 'text-amber-400'
      return 'text-red-400'
    }
    return 'text-gray-600'
  }

  return { dotClass, badgeClass, statusLabel, formatTarget, uptimeColor, responseTimeColor }
}
