// Status dots, tokenized (VELOURS). Badge + label now live in <StatusBadge>.
const statusDot = {
  up:      'bg-(--up)',
  down:    'bg-(--down)',
  timeout: 'bg-(--warn)',
  error:   'bg-(--error)',
}

/**
 * Pure row-display helpers for the monitor list (status dot, target
 * formatting, uptime / response-time colors). The status pill itself is
 * rendered by <StatusBadge>.
 */
export function useMonitorDisplay() {
  function dotClass(s) { return statusDot[s] ?? 'bg-(--text-3)' }

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

  return { dotClass, formatTarget, uptimeColor, responseTimeColor }
}
