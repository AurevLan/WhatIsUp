// Shared TLS grade (A+..F) presentation helpers.
//
// F7 (plan cap v2, 6c) folded the standalone TLS Fleet page into a
// MonitorsView "Certificates" view (components/monitors/CertificatesPanel.vue)
// and kept the grade visible on the monitor detail page
// (components/monitors/detail/MonitorConfigCards.vue). Both need the exact
// same grade → color mapping, so it lives here once instead of twice.
const GRADE_PALETTE = {
  'A+': 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)',
  A: 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)',
  B: 'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn)',
  C: 'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn)',
  D: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
  E: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
  F: 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)',
}

export function tlsGradeClass(grade) {
  return GRADE_PALETTE[grade] || 'bg-(--bg-surface-2) text-(--text-2)'
}

export function tlsDaysClass(days) {
  if (days == null) return 'text-(--text-3)'
  if (days < 14) return 'text-(--down) font-bold'
  if (days < 30) return 'text-(--warn)'
  return 'text-(--text-2)'
}
