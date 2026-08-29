// Tab state for MonitorDetailView.
//
// `viewTabs` reacts to the loaded monitor (scenario, map, runbook tabs only
// appear when relevant) and to whether at least one custom metric has been
// pushed. `setTab` ensures the Map tab triggers its lazy data load + Leaflet
// init via the `onMapActivated` callback — the parent owns the actual map
// reference; the composable only signals when to wake it up.

import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

export const TAB_AVAILABILITY = 'availability'
export const TAB_SCENARIO = 'scenario'
export const TAB_MAP = 'map'
export const TAB_ALERTS = 'alerts'
export const TAB_METRICS = 'metrics'
export const TAB_RUNBOOK = 'runbook'

export function useMonitorTabs(monitorRef, customMetricsRef, { onMapActivated } = {}) {
  const { t } = useI18n()

  const activeTab = ref(TAB_AVAILABILITY)

  const tabLabel = (tab) =>
    ({
      [TAB_AVAILABILITY]: t('monitor_detail.tab_availability'),
      [TAB_SCENARIO]: t('monitor_detail.tab_scenario'),
      [TAB_MAP]: t('monitor_detail.tab_map'),
      [TAB_ALERTS]: t('monitor_detail.tab_alerts'),
      [TAB_METRICS]: t('metrics.title'),
      [TAB_RUNBOOK]: t('runbook.tab_label'),
    }[tab] ?? tab)

  const viewTabs = computed(() => {
    const tabs = [TAB_AVAILABILITY]
    if (monitorRef.value?.check_type === 'scenario') tabs.push(TAB_SCENARIO)
    // Map only for types that use probes
    if (!['heartbeat', 'composite', 'domain_expiry'].includes(monitorRef.value?.check_type)) {
      tabs.push(TAB_MAP)
    }
    tabs.push(TAB_ALERTS)
    // Always shown — a monitor can push metrics before it ever appears here,
    // and hiding the tab until the first push left the feature undiscoverable
    // (chantier ergonomie, item 5b). The tab's own empty state now explains
    // the feature and links to the push URL, so there's nothing left to gate.
    tabs.push(TAB_METRICS)
    // Runbook tab — only when enabled on the monitor
    if (monitorRef.value?.runbook_enabled) tabs.push(TAB_RUNBOOK)
    return tabs
  })

  // Auto-switch to Scenario tab when monitor loads and is scenario type
  watch(
    monitorRef,
    (m) => {
      if (m?.check_type === 'scenario' && activeTab.value === TAB_AVAILABILITY) {
        activeTab.value = TAB_SCENARIO
      }
    },
    { once: true },
  )

  async function setTab(tab) {
    activeTab.value = tab
    if (tab === TAB_MAP && typeof onMapActivated === 'function') {
      await onMapActivated()
    }
  }

  return {
    TAB_AVAILABILITY,
    TAB_SCENARIO,
    TAB_MAP,
    TAB_ALERTS,
    TAB_METRICS,
    TAB_RUNBOOK,
    activeTab,
    viewTabs,
    tabLabel,
    setTab,
  }
}
