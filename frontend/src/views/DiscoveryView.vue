<template>
  <div class="page-body max-w-6xl">
    <div class="flex items-start justify-between mb-4">
      <div>
        <h1 class="font-display text-xl font-bold" style="color:var(--text-1)">{{ t('discovery.title') }}</h1>
        <p class="mt-0.5 text-xs" style="color:var(--text-3)">{{ t('discovery.subtitle') }}</p>
      </div>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b border-(--border)">
      <button
        v-for="tab in tabs" :key="tab.key"
        @click="activeTab = tab.key"
        class="px-4 py-2 text-sm font-medium transition-colors"
        :class="activeTab === tab.key
          ? 'text-(--accent) border-b-2 border-(--accent-border) -mb-px'
          : 'text-(--text-3) hover:text-(--text-1)'"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ── Sources tab ─────────────────────────────────────────────────────── -->
    <div v-if="activeTab === 'sources'">
      <div class="filter-bar">
        <button @click="openCreateSource" class="btn-primary btn-sm flex items-center gap-1.5">
          <Plus class="w-3.5 h-3.5" /> {{ t('discovery.add_source') }}
        </button>
      </div>

      <div v-if="loadingSources" class="card p-0 overflow-hidden">
        <div class="p-4 space-y-3">
          <SkeletonRow v-for="i in 3" :key="i" trailing-width="5rem" />
        </div>
      </div>

      <EmptyState
        v-else-if="sources.length === 0"
        :title="t('discovery.no_sources')"
        :text="t('empty.discovery_sources_text')"
        :cta-label="t('discovery.add_source')"
        @cta="openCreateSource"
      >
        <template #icon><Radar :size="22" /></template>
      </EmptyState>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div v-for="source in sources" :key="source.id" class="card">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="badge" :class="source.enabled ? 'badge-up' : 'badge-unknown'">
                  {{ source.enabled ? t('discovery.enabled_label') : t('discovery.disabled_label') }}
                </span>
                <span class="text-xs font-mono uppercase px-1.5 py-0.5 rounded bg-(--bg-surface-2) text-(--text-2)">
                  {{ t(`discovery.source_type_${source.source_type}`) }}
                </span>
              </div>
              <p class="text-sm font-semibold text-(--text-1) mt-1.5 truncate">{{ sourceTargetLabel(source) }}</p>
              <p v-if="source.source_type === 'port_scan'" class="text-xs text-(--text-3) font-mono mt-0.5 truncate">
                {{ source.params.cidr }} · {{ (source.params.ports || []).join(', ') }}
              </p>
              <!-- plan E, E-2 — fail-visible: a group-targeted source with no
                   currently-capable member can never run. -->
              <p v-if="source.probe_group_id && source.group_capable_probe_count === 0" class="text-xs text-(--down) mt-1 flex items-center gap-1">
                <TriangleAlert class="w-3 h-3" /> {{ t('discovery.group_capacity_warning') }}
              </p>
            </div>
            <div class="flex items-center gap-1 flex-shrink-0">
              <button
                class="btn-icon"
                :class="source.enabled ? 'btn-icon--active' : ''"
                :title="source.enabled ? t('discovery.disable') : t('discovery.enable')"
                :aria-label="source.enabled ? t('discovery.disable') : t('discovery.enable')"
                @click="toggleSourceEnabled(source)"
              >
                <Power class="w-3.5 h-3.5" />
              </button>
              <button class="btn-icon" :title="t('common.edit')" :aria-label="t('common.edit')" @click="editingSource = source">
                <PencilLine class="w-3.5 h-3.5" />
              </button>
              <button class="btn-icon" :title="t('common.delete')" :aria-label="t('common.delete')" @click="confirmDeleteSource(source)">
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <!-- Scan feedback (plan E, E-1) -->
          <div class="mt-3 pt-3 border-t border-(--border) flex items-center justify-between gap-2 flex-wrap">
            <p class="text-xs text-(--text-3) truncate">
              <template v-if="source.last_scan_at">
                {{ t('discovery.last_scan_prefix', { when: formatRelative(source.last_scan_at) }) }}
                · {{ t('discovery.last_scan_targets', source.last_scan_target_count || 0) }}
              </template>
              <template v-else>{{ t('discovery.never_scanned') }}</template>
            </p>
            <button
              class="btn-secondary btn-sm flex items-center gap-1.5 flex-shrink-0"
              :disabled="isScanPending(source)"
              @click="scanNow(source)"
            >
              <RefreshCw class="w-3.5 h-3.5" :class="isScanPending(source) ? 'animate-spin' : ''" />
              {{ isScanPending(source) ? t('discovery.scan_pending') : t('discovery.scan_now') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Review tab ──────────────────────────────────────────────────────── -->
    <div v-else>
      <!-- Bulk bar -->
      <BulkActionBar :count="selectedIds.size" @clear="clearSelection">
        <button @click="openBulkDismiss" class="btn-danger btn-sm flex items-center gap-1.5">
          <X class="w-3.5 h-3.5" /> {{ t('discovery.bulk_dismiss') }}
        </button>
        <button @click="bulkAccept" class="btn-primary btn-sm flex items-center gap-1.5">
          <Check class="w-3.5 h-3.5" /> {{ t('discovery.bulk_accept') }}
        </button>
      </BulkActionBar>

      <!-- Filters -->
      <div class="filter-bar">
        <select v-model="filterStatus" class="input h-8 text-xs" style="max-width:10rem" @change="loadServices">
          <option value="proposed">{{ t('discovery.status_proposed') }}</option>
          <option value="accepted">{{ t('discovery.status_accepted') }}</option>
          <option value="dismissed">{{ t('discovery.status_dismissed') }}</option>
          <option value="orphaned">{{ t('discovery.status_orphaned') }}</option>
          <option value="">{{ t('discovery.all_statuses') }}</option>
        </select>
        <select v-model="filterSourceId" class="input h-8 text-xs" style="max-width:12rem" @change="loadServices">
          <option value="">{{ t('discovery.all_sources') }}</option>
          <option v-for="source in sources" :key="source.id" :value="source.id">
            {{ sourceTargetLabel(source) }} · {{ t(`discovery.source_type_${source.source_type}`) }}
          </option>
        </select>
      </div>

      <div v-if="loadingServices" class="card p-0 overflow-hidden">
        <div class="p-4 space-y-3">
          <SkeletonRow v-for="i in 4" :key="i" trailing-width="5rem" />
        </div>
      </div>

      <EmptyState
        v-else-if="services.length === 0"
        :title="t('discovery.no_services')"
        :text="t('empty.discovery_services_text')"
      >
        <template #icon><Radar :size="22" /></template>
      </EmptyState>

      <div v-else class="card p-0 overflow-hidden">
        <!-- Mobile: stacked cards -->
        <div class="md:hidden flex flex-col divide-y divide-(--border)">
          <div v-for="service in services" :key="'c-' + service.id" class="px-4 py-4">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2 mb-1 flex-wrap">
                  <span class="badge" :class="statusBadgeClass(service.status)">{{ t(`discovery.status_${service.status}`) }}</span>
                  <span class="font-mono text-xs text-(--text-3) truncate">{{ service.normalized_target }}</span>
                </div>
                <p class="text-sm font-semibold text-(--text-1) truncate">{{ service.suggested_name }}</p>
                <p class="text-xs text-(--text-3) uppercase">{{ service.suggested_check_type }}</p>
                <router-link v-if="service.monitor_id" :to="`/monitors/${service.monitor_id}`" class="text-xs text-(--accent)">
                  {{ t('discovery.view_monitor') }}
                </router-link>
                <p v-if="service.dismissed_reason" class="text-xs text-(--text-3) mt-1">{{ t('discovery.reason_label') }}: {{ service.dismissed_reason }}</p>
              </div>
              <input
                v-if="isActionable(service)"
                type="checkbox"
                class="w-5 h-5 rounded border-(--border-hover) mt-1"
                :checked="selectedIds.has(service.id)"
                @change="toggleSelect(service.id)"
              />
            </div>
            <div v-if="isActionable(service)" class="flex items-center gap-2 mt-3">
              <button class="btn-secondary btn-sm flex-1 flex items-center justify-center gap-1.5" @click="openDismiss(service)">
                <X class="w-3.5 h-3.5" /> {{ t('discovery.dismiss') }}
              </button>
              <button class="btn-primary btn-sm flex-1 flex items-center justify-center gap-1.5" @click="acceptingService = service">
                <Check class="w-3.5 h-3.5" /> {{ t('discovery.accept') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Desktop: dense table -->
        <table class="hidden md:table w-full">
          <thead class="border-b border-(--border)">
            <tr>
              <th class="th pl-4 w-8">
                <input
                  type="checkbox"
                  class="w-4 h-4 rounded border-(--border-hover)"
                  :checked="allActionableSelected"
                  @change="toggleSelectAll"
                />
              </th>
              <th class="th">{{ t('common.status') }}</th>
              <th class="th">{{ t('discovery.col_target') }}</th>
              <th class="th">{{ t('discovery.col_suggestion') }}</th>
              <th class="th pr-6 text-right">{{ t('common.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="service in services" :key="service.id" class="table-row">
              <td class="td pl-4 w-8">
                <input
                  v-if="isActionable(service)"
                  type="checkbox"
                  class="w-4 h-4 rounded border-(--border-hover)"
                  :checked="selectedIds.has(service.id)"
                  @change="toggleSelect(service.id)"
                />
              </td>
              <td class="td">
                <span class="badge" :class="statusBadgeClass(service.status)">{{ t(`discovery.status_${service.status}`) }}</span>
                <p v-if="service.dismissed_reason" class="text-xs text-(--text-3) mt-1">{{ service.dismissed_reason }}</p>
              </td>
              <td class="td font-mono text-xs">
                {{ service.normalized_target }}
                <router-link v-if="service.monitor_id" :to="`/monitors/${service.monitor_id}`" class="block text-(--accent) mt-0.5">
                  {{ t('discovery.view_monitor') }}
                </router-link>
              </td>
              <td class="td">
                <span class="text-xs px-1.5 py-0.5 rounded bg-(--bg-surface-2) text-(--text-2) uppercase mr-1.5">{{ service.suggested_check_type }}</span>
                {{ service.suggested_name }}
              </td>
              <td class="td pr-6">
                <div v-if="isActionable(service)" class="flex items-center justify-end gap-1.5">
                  <button class="btn-icon" :title="t('discovery.dismiss')" :aria-label="t('discovery.dismiss')" @click="openDismiss(service)">
                    <X class="w-3.5 h-3.5" />
                  </button>
                  <button class="btn-icon" :title="t('discovery.accept')" :aria-label="t('discovery.accept')" @click="acceptingService = service">
                    <Check class="w-3.5 h-3.5" />
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <DiscoverySourceModal
      v-if="showSourceModal || editingSource"
      :probes="probes"
      :probe-groups="probeGroups"
      :source="editingSource"
      @close="closeSourceModal"
      @saved="onSourceSaved"
    />

    <DiscoveryAcceptModal
      v-if="acceptingService"
      :service="acceptingService"
      @close="acceptingService = null"
      @accepted="onAccepted"
    />

    <DiscoveryDismissModal
      v-if="dismissTarget"
      :count="dismissTarget === 'bulk' ? selectedIds.size : 1"
      @close="dismissTarget = null"
      @confirm="onDismissConfirm"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Check, PencilLine, Plus, Power, Radar, RefreshCw, Trash2, TriangleAlert, X } from 'lucide-vue-next'
import { discoveryApi } from '../api/discovery'
import { probesApi } from '../api/probes'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useDateFormat } from '../composables/useDateFormat'
import BulkActionBar from '../components/shared/BulkActionBar.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import SkeletonRow from '../components/shared/SkeletonRow.vue'
import DiscoverySourceModal from '../components/discovery/DiscoverySourceModal.vue'
import DiscoveryAcceptModal from '../components/discovery/DiscoveryAcceptModal.vue'
import DiscoveryDismissModal from '../components/discovery/DiscoveryDismissModal.vue'

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()
const { formatRelative } = useDateFormat()

// Scan feedback polling interval (plan E, E-1) — light polling of the sources
// list while a scan is pending, no WebSocket for this.
const SCAN_POLL_INTERVAL_MS = 4000
// Give up watching after this long (scan-now's latency is "one heartbeat",
// documented as ~15s — this is a generous multiple, not a real deadline) so a
// probe that never comes back doesn't spin the button forever.
const SCAN_POLL_MAX_MS = 120000

const tabs = computed(() => [
  { key: 'review', label: t('discovery.tab_review') },
  { key: 'sources', label: t('discovery.tab_sources') },
])
const activeTab = ref('review')

// ── Sources ───────────────────────────────────────────────────────────────
const sources = ref([])
const probes = ref([])
// plan E, E-2 — probe groups the caller may target a source at.
const probeGroups = ref([])
const loadingSources = ref(true)
const showSourceModal = ref(false)
const editingSource = ref(null)

function probeName(probeId) {
  return probes.value.find((p) => p.id === probeId)?.name || probeId
}

function groupName(groupId) {
  return probeGroups.value.find((g) => g.id === groupId)?.name || groupId
}

// A source targets either a probe or a probe group (plan E, E-2) — one
// label covers both without callers having to branch every time.
function sourceTargetLabel(source) {
  return source.probe_group_id ? groupName(source.probe_group_id) : probeName(source.probe_id)
}

async function loadProbes() {
  try {
    const { data } = await probesApi.list({ skipErrorToast: true })
    probes.value = data
  } catch {
    probes.value = []
  }
}

async function loadProbeGroups() {
  try {
    const { data } = await discoveryApi.probeGroups.list({ skipErrorToast: true })
    probeGroups.value = data
  } catch {
    probeGroups.value = []
  }
}

async function loadSources({ silent = false } = {}) {
  if (!silent) loadingSources.value = true
  try {
    const { data } = await discoveryApi.sources.list({ skipErrorToast: true })
    sources.value = data
  } catch {
    if (!silent) sources.value = []
  } finally {
    if (!silent) loadingSources.value = false
  }
}

// ── Scan now (plan E, E-1) ───────────────────────────────────────────────────
const pendingScanIds = ref(new Set())
// sourceId -> the `last_scan_at` value observed when the scan was requested —
// the poll below watches for it to change, which is how "scan finished"
// is detected without a WebSocket.
const scanBaselines = ref({})
let scanPollTimer = null
let scanPollDeadline = 0

function isScanPending(source) {
  return pendingScanIds.value.has(source.id)
}

function stopScanPolling() {
  if (scanPollTimer) {
    clearInterval(scanPollTimer)
    scanPollTimer = null
  }
}

function startScanPolling() {
  if (scanPollTimer) return
  scanPollDeadline = Date.now() + SCAN_POLL_MAX_MS
  scanPollTimer = setInterval(async () => {
    await loadSources({ silent: true })
    const next = new Set(pendingScanIds.value)
    for (const id of pendingScanIds.value) {
      const src = sources.value.find((s) => s.id === id)
      if (!src || src.last_scan_at !== scanBaselines.value[id]) {
        next.delete(id)
      }
    }
    pendingScanIds.value = next
    if (pendingScanIds.value.size === 0 || Date.now() > scanPollDeadline) {
      pendingScanIds.value = new Set()
      stopScanPolling()
    }
  }, SCAN_POLL_INTERVAL_MS)
}

async function scanNow(source) {
  if (isScanPending(source)) return
  // Optimistic: mark pending (and freeze the baseline to compare polls
  // against) before the request even resolves, so the button reflects
  // "working on it" immediately rather than only after a network round-trip.
  scanBaselines.value = { ...scanBaselines.value, [source.id]: source.last_scan_at ?? null }
  const next = new Set(pendingScanIds.value)
  next.add(source.id)
  pendingScanIds.value = next
  try {
    await discoveryApi.sources.scanNow(source.id, { skipErrorToast: true })
    success(t('discovery.scan_queued'))
    startScanPolling()
  } catch {
    toastError(t('common.error'))
    const reverted = new Set(pendingScanIds.value)
    reverted.delete(source.id)
    pendingScanIds.value = reverted
  }
}

function openCreateSource() {
  editingSource.value = null
  showSourceModal.value = true
}

function closeSourceModal() {
  showSourceModal.value = false
  editingSource.value = null
}

function onSourceSaved() {
  closeSourceModal()
  loadSources()
  success(t('discovery.source_saved'))
}

async function toggleSourceEnabled(source) {
  try {
    const { data } = await discoveryApi.sources.update(
      source.id,
      { enabled: !source.enabled },
      { skipErrorToast: true }
    )
    const idx = sources.value.findIndex((s) => s.id === source.id)
    if (idx !== -1) sources.value[idx] = data
  } catch {
    toastError(t('common.error'))
  }
}

async function confirmDeleteSource(source) {
  const ok = await confirm({
    title: t('discovery.confirm_delete_source'),
    message: t('discovery.confirm_delete_source_detail'),
    confirmLabel: t('common.delete'),
  })
  if (!ok) return
  try {
    await discoveryApi.sources.remove(source.id, { skipErrorToast: true })
    sources.value = sources.value.filter((s) => s.id !== source.id)
    success(t('discovery.source_deleted'))
  } catch {
    toastError(t('common.error'))
  }
}

// ── Review ────────────────────────────────────────────────────────────────
const services = ref([])
const loadingServices = ref(true)
const filterStatus = ref('proposed')
const filterSourceId = ref('')
const selectedIds = ref(new Set())
const acceptingService = ref(null)
// null | 'bulk' | a single service object
const dismissTarget = ref(null)

// Only a proposed/orphaned service can be accepted/dismissed (mirrors the
// server's `_TRANSITIONABLE_FROM` — plan D, D-3).
function isActionable(service) {
  return service.status === 'proposed' || service.status === 'orphaned'
}

const STATUS_BADGE = {
  proposed: 'badge-unknown',
  accepted: 'badge-up',
  dismissed: 'badge-error',
  orphaned: 'badge-timeout',
}
function statusBadgeClass(status) {
  return STATUS_BADGE[status] || 'badge-unknown'
}

const actionableServices = computed(() => services.value.filter(isActionable))
const allActionableSelected = computed(
  () => actionableServices.value.length > 0 && actionableServices.value.every((s) => selectedIds.value.has(s.id))
)

async function loadServices() {
  loadingServices.value = true
  clearSelection()
  try {
    const params = {}
    if (filterStatus.value) params.status = filterStatus.value
    if (filterSourceId.value) params.source_id = filterSourceId.value
    const { data } = await discoveryApi.services.list(params, { skipErrorToast: true })
    services.value = data
  } catch {
    services.value = []
  } finally {
    loadingServices.value = false
  }
}

function toggleSelect(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  if (allActionableSelected.value) {
    clearSelection()
  } else {
    selectedIds.value = new Set(actionableServices.value.map((s) => s.id))
  }
}

function clearSelection() {
  selectedIds.value = new Set()
}

function openDismiss(service) {
  dismissTarget.value = service
}

function openBulkDismiss() {
  if (selectedIds.value.size === 0) return
  dismissTarget.value = 'bulk'
}

async function onDismissConfirm(reason) {
  if (dismissTarget.value === 'bulk') {
    await runBulk('dismiss', reason)
  } else {
    const service = dismissTarget.value
    try {
      await discoveryApi.services.dismiss(service.id, { reason }, { skipErrorToast: true })
      success(t('discovery.dismiss_success'))
      loadServices()
    } catch {
      toastError(t('common.error'))
    }
  }
  dismissTarget.value = null
}

async function bulkAccept() {
  if (selectedIds.value.size === 0) return
  await runBulk('accept')
}

async function runBulk(action, reason) {
  try {
    const payload = { action, service_ids: Array.from(selectedIds.value) }
    if (reason) payload.reason = reason
    const { data } = await discoveryApi.services.bulk(payload, { skipErrorToast: true })
    const results = data.results || []
    const okCount = results.filter((r) => r.ok).length
    const failCount = results.length - okCount
    if (failCount === 0) {
      success(t('discovery.bulk_success', { n: okCount }))
    } else {
      toastError(t('discovery.bulk_partial', { ok: okCount, fail: failCount }))
    }
    clearSelection()
    loadServices()
  } catch {
    toastError(t('common.error'))
  }
}

function onAccepted() {
  acceptingService.value = null
  success(t('discovery.accept_success'))
  loadServices()
}

onMounted(() => {
  loadProbes()
  loadProbeGroups()
  loadSources()
  loadServices()
})

onUnmounted(() => {
  stopScanPolling()
})
</script>
