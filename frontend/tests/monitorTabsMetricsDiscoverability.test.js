/**
 * Metrics tab discoverability (chantier ergonomie, item 5b).
 *
 * The Metrics tab used to appear only once at least one metric had been
 * pushed for the monitor — so nothing in the UI hinted the feature existed
 * before its first use. The tab is now always shown; its own empty state
 * (MonitorCustomMetricsPanel) explains the feature and links to the push URL.
 */

import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k) => k }),
}))

import { useMonitorTabs, TAB_METRICS } from '../src/composables/useMonitorTabs'

describe('useMonitorTabs — metrics tab discoverability', () => {
  it('shows the Metrics tab even when no metric has ever been pushed', () => {
    const monitor = ref({ check_type: 'http' })
    const customMetrics = ref([])
    const { viewTabs } = useMonitorTabs(monitor, customMetrics)
    expect(viewTabs.value).toContain(TAB_METRICS)
  })

  it('keeps showing it once metrics exist', () => {
    const monitor = ref({ check_type: 'http' })
    const customMetrics = ref([{ metric_name: 'orders_per_minute' }])
    const { viewTabs } = useMonitorTabs(monitor, customMetrics)
    expect(viewTabs.value).toContain(TAB_METRICS)
  })
})
