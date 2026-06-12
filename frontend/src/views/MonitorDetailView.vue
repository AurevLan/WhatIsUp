<template>
  <div class="page-body" v-if="monitor">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <nav class="breadcrumbs">
        <router-link to="/monitors">{{ t('monitors.title') }}</router-link>
        <span class="breadcrumbs__sep">/</span>
        <span class="breadcrumbs__current">{{ monitor.name }}</span>
      </nav>
      <div class="flex-1">
        <div class="flex items-center gap-3">
          <span class="w-3 h-3 rounded-full" :class="statusClass"></span>
          <h1 class="text-2xl font-bold text-white">{{ monitor.name }}</h1>
        </div>
        <p class="text-gray-400 text-sm mt-1 font-mono">
          <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 uppercase mr-2">{{ monitor.check_type }}</span>
          {{ formatTarget(monitor) }}
        </p>
        <div class="mt-2">
          <TagChips :model-value="monitor.tags || []" @update:model-value="onTagsChange" />
        </div>
      </div>
    </div>

    <!-- No alert rules banner + auto-alert setup modal -->
    <MonitorAlertSetupBanner />

    <!-- View tabs -->
    <div class="flex gap-1 mb-6 border-b border-gray-800">
      <button
        v-for="tab in viewTabs" :key="tab"
        @click="setTab(tab)"
        class="px-4 py-2 text-sm font-medium transition-colors"
        :class="activeTab === tab
          ? 'text-blue-400 border-b-2 border-blue-400 -mb-px'
          : 'text-gray-500 hover:text-gray-300'"
      >
        {{ tabLabel(tab) }}
      </button>
    </div>

    <!-- ── Onglet Scénario ───────────────────────────────────────────────────── -->
    <MonitorScenarioTab
      v-if="activeTab === TAB_SCENARIO"
      :uptime24="uptime24"
      :uptime7d="uptime7d"
      :results="results"
      v-model:selected-run-id="selectedRunId"
      :new-result-id="newResultId"
      :testing="testing"
      :testing-state="testingState"
      :testing-elapsed="testingElapsed"
      :format-date="formatDate"
      :probe-color="probeColor"
      :probe-name="probeName"
      :step-type-badge-class="stepTypeBadgeClass"
      @trigger-check="handleTriggerCheck"
      @duplicate="duplicateMonitor"
      @schedule-maintenance="openScheduleMaintenance"
      @edit-monitor="editingMonitor = monitor"
      @open-screenshot="e => openScreenshot(e.src, e.label)"
    />

    <!-- ── Disponibilité + Temps de réponse + Checks ─────────────────────── -->
    <div v-if="activeTab === TAB_AVAILABILITY">

    <!-- Stats cards -->
    <MonitorStatsCards
      :uptime24="uptime24"
      :uptime7d="uptime7d"
      :is-dns="isDns"
      :is-network="isNetwork"
      :has-response-time="hasResponseTime"
      :dns-changelog="dnsChangelog"
      :response-trend="responseTrend"
      :format-date-short="formatDateShort"
    />

    <!-- DNS: current resolved value banner -->
    <MonitorDnsValueBanner v-if="isDns" :monitor="monitor" :format-target="formatTarget" />

    <!-- Annual uptime heatmap -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.heatmap_title') }}</h2>
        <span class="text-xs text-gray-500">365 {{ t('common.days') }}</span>
      </div>
      <UptimeHeatmap :monitor-id="String(monitor.id)" />
    </div>

    <!-- DNS: value changelog + drift card + alert suggestion modal -->
    <MonitorDnsPanel
      v-if="isDns"
      :monitor="monitor"
      :format-target="formatTarget"
      :format-date="formatDate"
      :probe-color="probeColor"
      :probe-name="probeName"
    />

    <!-- Network scope / schema drift / composite / headers / SSL / domain expiry -->
    <MonitorConfigCards
      :monitor="monitor"
      :results="results"
      :is-http-like="isHttpLike"
      :is-composite="isComposite"
      :is-domain-expiry="isDomainExpiry"
      :has-network-scope="hasNetworkScope"
      :fmt-date-time="fmtDateTime"
      :format-date-short="formatDateShort"
    />

    <!-- Incidents + Post-mortem + SLA Report -->
    <MonitorIncidentsTab
      :health-state="healthState"
      :fmt-date-time="fmtDateTime"
    />

    <!-- Chart window selector (shared by availability + RT charts) -->
    <div class="flex items-center gap-1 mb-3">
      <button
        v-for="w in CHART_WINDOWS" :key="w.h"
        @click="chartWindow = w.h"
        class="px-2.5 py-1 text-xs rounded-md border transition-colors"
        :class="chartWindow === w.h
          ? 'bg-blue-600 border-blue-500 text-white'
          : 'border-gray-700 text-gray-500 hover:border-gray-600 hover:text-gray-300'"
      >{{ w.label }}</button>
    </div>

    <!-- Availability timeline -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.availability') }}</h2>
        <span class="text-xs text-gray-500">{{ chartBucketMin(chartWindow) }}min {{ t('monitor_detail.buckets') }}</span>
      </div>
      <apexchart
        v-if="availSeries[0]?.data?.length"
        type="bar"
        height="140"
        :options="availOptions"
        :series="availSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">{{ t('monitor_detail.no_data') }}</p>
    </div>

    <!-- Response time per probe (HTTP/TCP/Keyword/JSON only — not DNS) -->
    <div v-if="hasResponseTime" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">
          {{ isNetwork ? t('monitor_detail.tcp_latency') : t('monitor_detail.response_time') }}
        </h2>
        <div class="flex items-center gap-3 flex-wrap">
          <span v-if="responseTrend" class="flex items-center gap-1 text-xs font-medium"
            :class="responseTrend.up ? 'text-red-400' : 'text-emerald-400'">
            {{ responseTrend.up ? '↑' : '↓' }} {{ responseTrend.pct }}% {{ t('monitor_detail.trend_vs_6h') }}
          </span>
          <span v-for="(s, i) in rtSeries" :key="s.name" class="flex items-center gap-1.5 text-xs text-gray-400">
            <span class="w-3 h-1.5 rounded-full inline-block" :style="`background:${probeColors[i % probeColors.length]}`" />
            {{ s.name }}
          </span>
        </div>
      </div>
      <apexchart
        v-if="rtSeries.length"
        type="line"
        height="220"
        :options="rtOptions"
        :series="rtSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">{{ t('monitor_detail.no_data') }}</p>
    </div>

    <!-- Response Time Percentiles (P50/P95/P99) -->
    <div v-if="percentilesData.length && hasResponseTime" class="card mb-6">
      <h3 class="text-sm font-semibold text-gray-300 mb-3">{{ t('monitor_detail.percentiles_title') }}</h3>
      <apexchart type="line" height="250" :options="percentileOptions" :series="percentileSeries" />
    </div>

    <!-- SLO panel (legacy SLO + V2 Health Engine) -->
    <MonitorSloPanel
      v-if="monitor"
      :monitor="monitor"
      :has-slo="hasSlo"
      :probe-name="probeName"
    />

    <!-- Annotations -->
    <MonitorAnnotationsPanel :fmt-date-time="fmtDateTime" />

    <!-- DNS: resolution history table -->
    <MonitorDnsResolutionsTable
      v-if="isDns"
      :monitor="monitor"
      :results="results"
      :format-date="formatDate"
      :probe-color="probeColor"
      :probe-name="probeName"
    />

    <!-- Recent checks table (HTTP / TCP / Keyword / JSON — not scenario, not dns) -->
    <MonitorRecentChecksTable
      v-if="hasRecentChecks"
      :monitor="monitor"
      :results="results"
      :no-http-types="noHttpTypes"
      :is-http-like="isHttpLike"
      :format-date="formatDate"
      :probe-color="probeColor"
      :probe-name="probeName"
    />

    <!-- Métriques custom push (card + modal URL de push) -->
    <MonitorCustomMetricsPanel :monitor="monitor" :api-base="apiBase" />

    </div><!-- end Disponibilité tab -->

    <!-- ── Dépendances (section commune, tous onglets) ──────────────────────── -->
    <div class="mt-8 card">
      <MonitorDependencies
        :monitor-id="String(monitor.id)"
        :all-monitors="allMonitors"
      />
    </div>

    <!-- ── Onglet Carte ─────────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_MAP">
      <div ref="probeMapEl" class="rounded-xl overflow-hidden" style="height: 480px;"></div>

      <!-- Sondes sans coordonnées -->
      <div v-if="probesWithoutCoords.length" class="mt-6">
        <h3 class="text-sm font-semibold text-gray-400 mb-3">{{ t('monitor_detail.unlocated_probes') }}</h3>
        <div class="space-y-2">
          <div v-for="p in probesWithoutCoords" :key="p.probe_id"
            class="flex items-center gap-3 text-sm text-gray-300">
            <span class="w-2 h-2 rounded-full" :class="markerColor(p).dot"></span>
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-gray-500">{{ p.location_name }}</span>
            <span class="text-xs" :class="markerColor(p).text">{{ statusLabel(p) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Onglet Alertes ────────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_ALERTS && monitor">
      <AlertMatrix :monitor-id="monitor.id" :check-type="monitor.check_type" />
    </div>

    <!-- ── Onglet Métriques ──────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_METRICS && monitor">
      <MetricsDashboard :monitor-id="String(monitor.id)" />
    </div>

    <!-- ── Onglet Runbook ───────────────────────────────────────────────────── -->
    <MonitorRunbookTab
      v-if="activeTab === TAB_RUNBOOK && monitor"
      :monitor="monitor"
      :editing="runbookEditing"
      v-model:draft="runbookDraft"
      :saving="runbookSaving"
      :rendered-html="runbookRenderedHtml"
      :preview-html="runbookPreviewHtml"
      @start-edit="startEditRunbook"
      @cancel-edit="cancelEditRunbook"
      @save="saveRunbook"
    />

    <!-- Screenshot lightbox (global — accessible depuis n'importe quel onglet) -->
    <BaseModal
      :model-value="screenshotModal.open"
      :title="screenshotModal.label || 'Screenshot'"
      size="xl"
      @update:model-value="screenshotModal.open = $event"
    >
      <img :src="screenshotModal.src" :alt="screenshotModal.label || 'Scenario screenshot'" class="w-full rounded-lg border border-gray-700 shadow-2xl" />
    </BaseModal>
    <EditMonitorModal v-if="editingMonitor" :monitor="editingMonitor" @close="editingMonitor = null" @updated="onMonitorUpdated" />
    <CreateMonitorModal v-if="showClone" :initial-data="clonePayload" @close="showClone = false" @created="onCloneCreated" />

    <!-- Quick schedule maintenance modal -->
    <MonitorMaintenanceModal />
  </div>
  <div v-else class="page-body" role="status" aria-busy="true" :aria-label="t('common.loading')">
    <!-- Skeleton header -->
    <div class="flex items-center gap-4 mb-8">
      <div class="flex-1 space-y-2">
        <SkeletonBox width="14rem" height="1.5rem" />
        <SkeletonBox width="20rem" height="0.75rem" />
      </div>
    </div>
    <!-- Skeleton tabs -->
    <div class="flex gap-3 mb-6 border-b border-gray-800 pb-2">
      <SkeletonBox v-for="i in 4" :key="i" width="5rem" height="1rem" />
    </div>
    <!-- Skeleton chart + cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div v-for="i in 3" :key="i" class="card">
        <SkeletonBox width="40%" height="0.7rem" />
        <div class="mt-3"><SkeletonBox width="60%" height="1.5rem" /></div>
      </div>
    </div>
    <div class="card">
      <SkeletonBox width="30%" height="0.85rem" />
      <div class="mt-4"><SkeletonBox width="100%" height="14rem" rounded="md" /></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, provide, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { monitorsApi } from '../api/monitors'
import BaseModal from '../components/BaseModal.vue'
import { getServerUrl } from '../lib/serverConfig.js'
import { useProbesStore } from '../stores/probes'
import MonitorDependencies from '../components/monitors/MonitorDependencies.vue'
import EditMonitorModal from '../components/monitors/EditMonitorModal.vue'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'
import UptimeHeatmap from '../components/monitors/UptimeHeatmap.vue'
import AlertMatrix from '../components/monitors/AlertMatrix.vue'
import TagChips from '../components/monitors/TagChips.vue'
import MetricsDashboard from '../components/monitors/MetricsDashboard.vue'
import SkeletonBox from '../components/shared/SkeletonBox.vue'
import { useCommandPaletteStore } from '../stores/commandPalette'
import { useTimezone } from '../composables/useTimezone'
import { useDateFormat } from '../composables/useDateFormat'
import { useMonitorRunbook } from '../composables/useMonitorRunbook'
import { useMonitorDependencies } from '../composables/useMonitorDependencies'
import { useMonitorIncidents } from '../composables/useMonitorIncidents'
import { useMonitorSlo } from '../composables/useMonitorSlo'
import { useMonitorTabs } from '../composables/useMonitorTabs'
import { useMonitorAnnotations } from '../composables/useMonitorAnnotations'
import { useMonitorPercentiles } from '../composables/useMonitorPercentiles'
import { useMonitorCustomMetrics } from '../composables/useMonitorCustomMetrics'
import { useMonitorCharts, PROBE_COLORS } from '../composables/useMonitorCharts'
import { useMonitorDns } from '../composables/useMonitorDns'
import { useMonitorAlerts } from '../composables/useMonitorAlerts'
import { useMonitorTesting } from '../composables/useMonitorTesting'
import { useMonitorMap } from '../composables/useMonitorMap'
import { useMonitorPatch } from '../composables/useMonitorPatch'
import { useMonitorMaintenance } from '../composables/useMonitorMaintenance'
import MonitorRunbookTab from '../components/monitors/detail/MonitorRunbookTab.vue'
import MonitorIncidentsTab from '../components/monitors/detail/MonitorIncidentsTab.vue'
import MonitorSloPanel from '../components/monitors/detail/MonitorSloPanel.vue'
import MonitorScenarioTab from '../components/monitors/detail/MonitorScenarioTab.vue'
import {
  IncidentsStateKey,
  SloStateKey,
  DnsStateKey,
  AnnotationsStateKey,
  CustomMetricsStateKey,
  AlertSetupStateKey,
  PatchStateKey,
  DependenciesStateKey,
  MaintenanceStateKey,
} from '../components/monitors/detail/injectionKeys'
import MonitorRecentChecksTable from '../components/monitors/detail/MonitorRecentChecksTable.vue'
import MonitorAlertSetupBanner from '../components/monitors/detail/MonitorAlertSetupBanner.vue'
import MonitorDnsValueBanner from '../components/monitors/detail/MonitorDnsValueBanner.vue'
import MonitorStatsCards from '../components/monitors/detail/MonitorStatsCards.vue'
import MonitorDnsPanel from '../components/monitors/detail/MonitorDnsPanel.vue'
import MonitorDnsResolutionsTable from '../components/monitors/detail/MonitorDnsResolutionsTable.vue'
import MonitorConfigCards from '../components/monitors/detail/MonitorConfigCards.vue'
import MonitorAnnotationsPanel from '../components/monitors/detail/MonitorAnnotationsPanel.vue'
import MonitorCustomMetricsPanel from '../components/monitors/detail/MonitorCustomMetricsPanel.vue'
import MonitorMaintenanceModal from '../components/monitors/detail/MonitorMaintenanceModal.vue'

const { t, locale } = useI18n()
const { format: tzFormat } = useTimezone()
const { formatDate: fmtDate, formatDateShort } = useDateFormat()
// Template shortcut — respects the user's timezone preference (T1-13).
// Drop-in replacement for `new Date(x).toLocaleString(locale)` inline calls.
const fmtDateTime = (v) =>
  v
    ? tzFormat(
        v,
        { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
        locale.value,
      )
    : ''

const route = useRoute()
const router = useRouter()
const paletteStore = useCommandPaletteStore()
const probesStore = useProbesStore()
const monitor   = ref(null)
const results   = ref([])
const uptime24  = ref(null)
const uptime7d  = ref(null)
const probeMap  = computed(() => probesStore.probeMap)
const editingMonitor = ref(null)
const showClone = ref(false)
const clonePayload = ref(null)

// ── Maintenance quick-schedule ─────────────────────────────────────────────
// Sub-component (MonitorMaintenanceModal) reads via inject(MaintenanceStateKey).
const maintenanceState = useMonitorMaintenance(monitor)
provide(MaintenanceStateKey, maintenanceState)
const { openSchedule: openScheduleMaintenance } = maintenanceState

function duplicateMonitor() {
  if (!monitor.value) return
  const m = { ...monitor.value }
  // Strip server-only / identity fields
  delete m.id
  delete m.created_at
  delete m.updated_at
  delete m.owner_id
  delete m.heartbeat_slug
  delete m.last_status
  delete m.is_paused
  delete m.group_id
  m.name = 'Copy of ' + m.name
  clonePayload.value = m
  showClone.value = true
}

function onCloneCreated() {
  showClone.value = false
  router.push('/monitors')
}

function onMonitorUpdated() {
  editingMonitor.value = null
  loadAll()
}

async function loadAll() {
  const id    = route.params.id
  const since = new Date(Date.now() - chartWindow.value * 60 * 60 * 1000).toISOString()
  const [monResp, resResp, up24Resp, up7dResp] = await Promise.all([
    monitorsApi.get(id),
    monitorsApi.results(id, { limit: 2000, since }),
    monitorsApi.uptime(id, 24),
    monitorsApi.uptime(id, 168),
  ])
  monitor.value  = monResp.data
  results.value  = resResp.data
  uptime24.value = up24Resp.data
  uptime7d.value = up7dResp.data
  loadPercentiles()
  loadHealthEngine(id)
}

// ── SLO panel (legacy SLO + V2 Health Engine) ────────────────────────────
// Sub-component reads via inject(SloStateKey); we only destructure what
// MonitorDetailView itself touches directly.
const sloState = useMonitorSlo(monitor)
provide(SloStateKey, sloState)
const { healthState, loadHealthEngine, loadSlo, sloEditTarget, sloEditDays } = sloState

// ── Incidents + Post-mortem + SLA Report ─────────────────────────────────────
const monitorIdRef = computed(() => route.params.id)
const incidentsState = useMonitorIncidents(monitor, monitorIdRef)
provide(IncidentsStateKey, incidentsState)
// `incidents` feeds useMonitorCharts annotations; loadIncidents fires on mount.
const { incidents, loadIncidents } = incidentsState

// ── Annotations ───────────────────────────────────────────────────────────────
// Sub-component (MonitorAnnotationsPanel) reads via inject(AnnotationsStateKey);
// `annotations` feeds useMonitorCharts, loadAnnotations fires on mount.
const annotationsState = useMonitorAnnotations(monitorIdRef)
provide(AnnotationsStateKey, annotationsState)
const { annotations, load: loadAnnotations } = annotationsState

// Percentiles P50/P95/P99 — instantiated below, after chartWindow is declared.

// "Tester maintenant" — trigger check + 30s polling: instantiated below,
// after chartWindow is declared.


// ── Scenario run selection ────────────────────────────────────────────────────
const selectedRunId = ref(null)

// ── Map (Carte tab) — Leaflet lazy-loaded on first activation ───────────────
const {
  probeMapEl,
  probesWithoutCoords,
  markerColor,
  statusLabel,
  loadAndInit: loadAndInitMap,
} = useMonitorMap(monitorIdRef)

const probeColors = PROBE_COLORS

// ── helpers ──────────────────────────────────────────────────────────────────
const statusMap  = { up: 'bg-emerald-400', down: 'bg-red-500', timeout: 'bg-amber-400', error: 'bg-orange-500' }
const statusClass = computed(() => statusMap[monitor.value?._lastStatus ?? monitor.value?.last_status] || 'bg-gray-600')

// ── Tendance temps de réponse ─────────────────────────────────────────────────
const responseTrend = computed(() => {
  if (!results.value.length) return null
  const now = Date.now()
  const h6  = 6 * 3600 * 1000
  const recent = results.value.filter(r =>
    r.response_time_ms != null && new Date(r.checked_at).getTime() > now - h6
  )
  const older = results.value.filter(r =>
    r.response_time_ms != null &&
    new Date(r.checked_at).getTime() <= now - h6 &&
    new Date(r.checked_at).getTime() > now - 2 * h6
  )
  if (recent.length < 3 || older.length < 3) return null
  const avgRecent = recent.reduce((s, r) => s + r.response_time_ms, 0) / recent.length
  const avgOlder  = older.reduce((s,  r) => s + r.response_time_ms, 0) / older.length
  const pct = ((avgRecent - avgOlder) / avgOlder) * 100
  if (Math.abs(pct) < 10) return null
  return { up: pct > 0, pct: Math.abs(pct).toFixed(0) }
})

// ── DNS (changelog, baseline, drift toggles, alert-suggestion modal) ─────────
// Sub-components (MonitorDnsValueBanner, MonitorDnsPanel,
// MonitorDnsResolutionsTable) read via inject(DnsStateKey);
// the view only needs changelog for the stats cards.
const dnsState = useMonitorDns(monitor, results)
provide(DnsStateKey, dnsState)
const { changelog: dnsChangelog } = dnsState

// Auto-select the most recent run when results load
watch(results, (res) => {
  if (monitor.value?.check_type === 'scenario' && res.length && !selectedRunId.value) {
    selectedRunId.value = res[0].id
  }
}, { immediate: true })

const screenshotModal = ref({ open: false, src: '', label: '' })

function openScreenshot(src, label) {
  screenshotModal.value = { open: true, src, label }
}

const STEP_TYPE_COLORS = {
  navigate:       'bg-blue-900/60 text-blue-300',
  click:          'bg-violet-900/60 text-violet-300',
  fill:           'bg-cyan-900/60 text-cyan-300',
  select:         'bg-cyan-900/60 text-cyan-300',
  hover:          'bg-violet-900/60 text-violet-300',
  scroll:         'bg-gray-800 text-gray-400',
  wait_element:   'bg-amber-900/60 text-amber-300',
  wait_time:      'bg-amber-900/60 text-amber-300',
  assert_text:    'bg-emerald-900/60 text-emerald-300',
  assert_visible: 'bg-emerald-900/60 text-emerald-300',
  assert_url:     'bg-emerald-900/60 text-emerald-300',
  screenshot:     'bg-pink-900/60 text-pink-300',
  group:          'bg-gray-700 text-gray-400',
  extract:        'bg-purple-900/60 text-purple-300',
}

function stepTypeBadgeClass(type) {
  return STEP_TYPE_COLORS[type] ?? 'bg-gray-800 text-gray-400'
}

// Map probe_id → ordered index (stable colors across renders)
const probeIndexMap = computed(() => {
  const ids = [...new Set(results.value.map(r => r.probe_id))]
  return Object.fromEntries(ids.map((id, i) => [id, i]))
})

function probeName(probeId) {
  const p = probeMap.value[probeId]
  return p ? p.location_name : probeId.slice(0, 8) + '…'
}

function probeColor(probeId) {
  const idx = probeIndexMap.value[probeId] ?? 0
  return probeColors[idx % probeColors.length]
}

// ── Chart window & alert threshold ────────────────────────────────────────────
const CHART_WINDOWS = [
  { h: 6,   label: '6h' },
  { h: 24,  label: '24h' },
  { h: 72,  label: '3d' },
  { h: 168, label: '7d' },
]
const chartWindow = ref(24)

// ── "Tester maintenant" — trigger check + 30s polling ───────────────────────
const {
  testing,
  testingState,
  newResultId,
  testingElapsed,
  loadResults,
  handleTriggerCheck,
} = useMonitorTesting(monitor, monitorIdRef, results, chartWindow)

// Reload results when chart window changes (watch must be after chartWindow declaration)
watch(chartWindow, () => { loadResults(); loadPercentiles() })

// ── Alert rules + auto-alert "no rules" banner setup ────────────────────────
// Sub-component (MonitorAlertSetupBanner) reads via inject(AlertSetupStateKey);
// `alertRules` feeds useMonitorCharts threshold annotations.
const alertSetupState = useMonitorAlerts(monitor)
provide(AlertSetupStateKey, alertSetupState)
const { rules: alertRules, loadRules: loadAlertRules } = alertSetupState

// ── Charts (RT line + Availability bar) ──────────────────────────────────────
const {
  rtSeries,
  rtOptions,
  availSeries,
  availOptions,
  chartBucketMin,
} = useMonitorCharts({
  results,
  incidents,
  annotations,
  alertRules,
  chartWindow,
  probeName,
})

// ── Custom metrics push ───────────────────────────────────────────────────────
// On native (Capacitor) window.location.origin is capacitor://localhost — the
// copy-paste curl snippet must use the configured server URL instead.
const apiBase = getServerUrl() || window.location.origin
// Sub-component (MonitorCustomMetricsPanel) reads via inject(CustomMetricsStateKey);
// `customMetrics` feeds useMonitorTabs (Métriques tab visibility).
const customMetricsState = useMonitorCustomMetrics(monitor)
provide(CustomMetricsStateKey, customMetricsState)
const { metrics: customMetrics, load: loadCustomMetrics } = customMetricsState

// ── Percentiles P50/P95/P99 ──────────────────────────────────────────────────
const {
  data: percentilesData,
  load: loadPercentiles,
  series: percentileSeries,
  options: percentileOptions,
} = useMonitorPercentiles(monitorIdRef, chartWindow)

// ── Tabs ─────────────────────────────────────────────────────────────────────
const {
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
} = useMonitorTabs(monitor, customMetrics, { onMapActivated: loadAndInitMap })


// ── Helpers ───────────────────────────────────────────────────────────────────
const noHttpTypes = ['tcp', 'udp', 'smtp', 'ping', 'domain_expiry', 'heartbeat', 'composite']

// ── Check type groups (controls section visibility) ─────────────────────────
const ct = computed(() => monitor.value?.check_type)
const isHttpLike = computed(() => ['http', 'keyword', 'json_path'].includes(ct.value))
const isNetwork = computed(() => ['tcp', 'udp', 'smtp', 'ping'].includes(ct.value))
const isDns = computed(() => ct.value === 'dns')
const isComposite = computed(() => ct.value === 'composite')
const isDomainExpiry = computed(() => ct.value === 'domain_expiry')
// Has response time data (chart + percentiles + stats cards)
const hasResponseTime = computed(() => isHttpLike.value || isNetwork.value)
// Has network scope selector
const hasNetworkScope = computed(() => isHttpLike.value || isNetwork.value || isDns.value)
// Has recent checks table
const hasRecentChecks = computed(() => isHttpLike.value || isNetwork.value)
// Has SLO
const hasSlo = computed(() => isHttpLike.value || isNetwork.value || isDns.value)

function formatTarget(m) {
  const raw = m.url?.replace(/^https?:\/\//, '') || ''
  if (m.check_type === 'tcp') return m.tcp_port ? `${raw}:${m.tcp_port}` : raw
  if (m.check_type === 'udp') return m.udp_port ? `${raw}:${m.udp_port}` : raw
  if (m.check_type === 'smtp') return m.smtp_port ? `${raw}:${m.smtp_port}` : raw
  if (m.check_type === 'scenario') {
    const firstNav = m.scenario_steps?.find(s => s.type === 'navigate')
    return firstNav?.params?.url?.replace(/^https?:\/\//, '') || 'scenario'
  }
  if (m.check_type === 'composite') return 'composite'
  if (m.check_type === 'heartbeat') return m.heartbeat_slug || 'heartbeat'
  return raw
}

const formatDate = (dt) =>
  fmtDate(dt, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    day: '2-digit', month: '2-digit',
  })

// ── Single-field patches: schema drift, tags, network scope ─────────────────
// Sub-component (MonitorConfigCards) reads via inject(PatchStateKey);
// the view only needs patchTags for the header TagChips.
const patchState = useMonitorPatch(monitor)
provide(PatchStateKey, patchState)
const { patchTags: onTagsChange } = patchState

// ── Runbook ──────────────────────────────────────────────────────────────────
const {
  editing: runbookEditing,
  draft: runbookDraft,
  saving: runbookSaving,
  renderedHtml: runbookRenderedHtml,
  previewHtml: runbookPreviewHtml,
  startEdit: startEditRunbook,
  cancelEdit: cancelEditRunbook,
  save: saveRunbook,
} = useMonitorRunbook(monitor)

// ── Dependencies & composite members ─────────────────────────────────────────
// Sub-component (MonitorConfigCards) reads via inject(DependenciesStateKey);
// the view only needs allMonitors (dependency picker) + the mount loaders.
const dependenciesState = useMonitorDependencies(monitor)
provide(DependenciesStateKey, dependenciesState)
const { allMonitors, loadAllMonitors, loadCompositeMembers } = dependenciesState

// (Cleanup handled by useMonitorTesting + useMonitorMap via onScopeDispose.)

// ── Mount ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
  const id   = route.params.id
  const since = new Date(Date.now() - chartWindow.value * 60 * 60 * 1000).toISOString()

  const [monResp, resResp, up24Resp, up7dResp] = await Promise.all([
    monitorsApi.get(id),
    monitorsApi.results(id, { limit: 2000, since }),
    monitorsApi.uptime(id, 24),
    monitorsApi.uptime(id, 168),
  ])
  monitor.value  = monResp.data
  results.value  = resResp.data
  uptime24.value = up24Resp.data
  uptime7d.value = up7dResp.data

  // Surface this monitor as a recent in the command palette (T1-10).
  paletteStore.recordVisit({
    type: 'monitor',
    id: monitor.value.id,
    name: monitor.value.name,
    route: `/monitors/${monitor.value.id}`,
  })

  // Initialise SLO edit refs from loaded monitor
  sloEditTarget.value = monitor.value.slo_target ?? null
  sloEditDays.value   = monitor.value.slo_window_days ?? 30

  // Load annotations, incidents, SLO, custom metrics, composite members & alert rules non-blocking
  loadAnnotations()
  loadIncidents()
  loadSlo()
  loadCustomMetrics()
  loadCompositeMembers()
  loadAlertRules()

  // Load all monitors for dependency picker
  loadAllMonitors()

  // Fetch probe names from shared store (cached across views, graceful fallback)
  probesStore.fetch()
})
</script>

<style scoped>
.breadcrumb { display: flex; align-items: center; gap: 6px; font-size: 0.8125rem; margin-bottom: 1.25rem; }
.breadcrumb__link { color: var(--text-3); transition: color .15s; }
.breadcrumb__link:hover { color: var(--text-1); }
.breadcrumb__sep { color: var(--text-3); }
.breadcrumb__current { color: var(--text-1); font-weight: 500; }

.runbook-preview { line-height: 1.55; }
.runbook-preview :deep(h1),
.runbook-preview :deep(h2),
.runbook-preview :deep(h3) { margin: .6rem 0 .35rem; color: var(--text-1); font-weight: 600; }
.runbook-preview :deep(h1) { font-size: 1.05rem; }
.runbook-preview :deep(h2) { font-size: .95rem; }
.runbook-preview :deep(h3) { font-size: .9rem; }
.runbook-preview :deep(p) { margin: .35rem 0; }
.runbook-preview :deep(ul),
.runbook-preview :deep(ol) { padding-left: 1.25rem; margin: .3rem 0; }
.runbook-preview :deep(li) { margin: .2rem 0; }
.runbook-preview :deep(code) {
  background: rgba(255,255,255,.08);
  padding: .1em .35em;
  border-radius: 3px;
  font-size: .85em;
}
.runbook-preview :deep(pre) {
  background: rgba(0,0,0,.4);
  padding: .7rem .9rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: .4rem 0;
}
.runbook-preview :deep(a) { color: #60a5fa; text-decoration: underline; }
.runbook-preview :deep(.runbook-task) { list-style: none; margin-left: -1rem; }
.runbook-preview :deep(.runbook-task input[type="checkbox"]) { margin-right: .45rem; }
</style>
