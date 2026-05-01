<template>
  <div class="incidents">

    <div class="incidents__header">
      <div>
        <h1 class="incidents__title">{{ t('incidents.title') }}</h1>
        <p class="incidents__sub">{{ t('incidents.subtitle') }}</p>
      </div>
    </div>

    <!-- Filters -->
    <div class="filter-bar">
      <div class="filter-group">
        <button
          v-for="opt in statusOpts"
          :key="opt.value"
          class="filter-chip"
          :class="{ 'filter-chip--active': statusFilter === opt.value }"
          @click="statusFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
      <div style="width:1px;height:1rem;background:var(--border);opacity:.6" />
      <div class="filter-group">
        <button
          v-for="opt in verdictOpts"
          :key="opt.value"
          class="filter-chip"
          :class="{ 'filter-chip--active': verdictFilter === opt.value }"
          :title="opt.title"
          @click="verdictFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
      <div style="width:1px;height:1rem;background:var(--border);opacity:.6" />
      <div class="filter-group">
        <button
          v-for="opt in dayOpts"
          :key="opt.value"
          class="filter-chip"
          :class="{ 'filter-chip--active': daysFilter === opt.value }"
          @click="daysFilter = opt.value"
        >{{ opt.label }}</button>
      </div>
      <button
        v-if="statusFilter !== 'all' || daysFilter !== 30"
        class="filter-clear"
        @click="resetFilters"
      >
        <X :size="12" /> {{ t('monitors.clear_filters') }}
      </button>
    </div>

    <!-- Bulk action bar (T1-12) -->
    <BulkActionBar :count="selectedIds.size" @clear="clearSelection">
      <button @click="bulkAck" class="btn-primary text-xs px-3 py-1.5 flex items-center gap-1.5">
        <CheckCircle class="w-3.5 h-3.5" /> {{ t('incidents.bulk_ack') }}
      </button>
    </BulkActionBar>

    <!-- List -->
    <div class="card p-0 overflow-hidden">
      <div v-if="loading" class="incidents__empty">
        <div v-for="i in 8" :key="i" class="skeleton h-14 mb-2" />
      </div>

      <div v-else-if="displayItems.length === 0" class="empty-state">
        <div class="empty-state__icon"><AlertCircle :size="22" /></div>
        <p class="empty-state__title">{{ t('incidents.no_incidents') }}</p>
      </div>

      <div v-else>
        <template v-for="item in displayItems" :key="item.key">

          <!-- ── Correlated group ──────────────────────────────────────── -->
          <div v-if="item.type === 'group'" class="inc-group">
            <button class="inc-group__header" @click="toggleGroup(item.group_id)">
              <span class="inc-group__icon">
                <Link2 :size="14" />
              </span>
              <span class="inc-group__summary">
                {{ t('incidents.correlated_summary', { count: item.incidents.length }) }}
                <span class="inc-group__cause" v-if="item.root_cause">
                  — {{ t('incidents.root_cause') }}:
                  <strong>{{ item.root_cause }}</strong>
                </span>
              </span>
              <span class="inc-group__type" :class="'inc-group__type--' + item.correlation_type">
                {{ correlationLabel(item.correlation_type) }}
              </span>
              <span class="inc-group__monitors">
                {{ item.monitor_names.join(', ') }}
              </span>
              <ChevronDown :size="14" class="inc-group__chevron" :class="{ 'inc-group__chevron--open': expandedGroups[item.group_id] }" />
            </button>

            <div v-if="expandedGroups[item.group_id]" class="inc-group__body">
              <div
                v-for="inc in item.incidents"
                :key="inc.id"
                class="inc-row inc-row--data inc-row--grouped"
              >
                <router-link :to="`/monitors/${inc.monitor_id}`" class="inc-col inc-col--status">
                  <span class="inc-badge" :class="badgeClass(inc)">{{ badgeLabel(inc) }}</span>
                  <span
                    v-if="verdictBadge(inc)"
                    class="inc-badge inc-badge--verdict"
                    :class="verdictBadgeClass(inc)"
                    :title="verdictTooltip(inc)"
                  >{{ verdictBadge(inc) }}</span>
                </router-link>
                <router-link :to="`/monitors/${inc.monitor_id}`" class="inc-col inc-col--monitor">{{ inc.monitor_name }}</router-link>
                <span class="inc-col inc-col--type">{{ inc.monitor_check_type }}</span>
                <span class="inc-col inc-col--started">{{ formatDate(inc.started_at) }}</span>
                <span class="inc-col inc-col--duration">{{ formatDuration(inc) }}</span>
                <span class="inc-col inc-col--actions">
                  <input
                    v-if="canSelect(inc)"
                    type="checkbox"
                    class="inc-checkbox"
                    :checked="selectedIds.has(inc.id)"
                    @click.stop
                    @change="toggleSelect(inc.id)"
                  />
                  <button v-if="!inc.is_resolved && !inc.acked_at" class="ack-btn" :title="t('incidents.acknowledge')" @click.prevent="ack(inc)"><CheckCircle :size="16" /></button>
                  <button v-else-if="!inc.is_resolved && inc.acked_at" class="ack-btn ack-btn--active" :title="t('incidents.unacknowledge')" @click.prevent="unack(inc)"><CheckCircle :size="16" /></button>
                </span>
              </div>
            </div>
          </div>

          <!-- ── Standalone incident ───────────────────────────────────── -->
          <div v-else>
            <div class="inc-row inc-row--data">
              <router-link :to="`/monitors/${item.monitor_id}`" class="inc-col inc-col--status">
                <span class="inc-badge" :class="badgeClass(item)">{{ badgeLabel(item) }}</span>
                <span
                  v-if="verdictBadge(item)"
                  class="inc-badge inc-badge--verdict"
                  :class="verdictBadgeClass(item)"
                  :title="verdictTooltip(item)"
                >{{ verdictBadge(item) }}</span>
              </router-link>
              <router-link :to="`/monitors/${item.monitor_id}`" class="inc-col inc-col--monitor">{{ item.monitor_name }}</router-link>
              <span class="inc-col inc-col--type">{{ item.monitor_check_type }}</span>
              <span class="inc-col inc-col--started">{{ formatDate(item.started_at) }}</span>
              <span class="inc-col inc-col--duration">{{ formatDuration(item) }}</span>
              <span class="inc-col inc-col--actions">
                <input
                  v-if="canSelect(item)"
                  type="checkbox"
                  class="inc-checkbox"
                  :checked="selectedIds.has(item.id)"
                  @click.stop
                  @change="toggleSelect(item.id)"
                />
                <button
                  v-if="hasRunbook(item)"
                  class="ack-btn"
                  :title="t('runbook.show_hide')"
                  @click.prevent="toggleRunbook(item.id)"
                >📖</button>
                <button
                  class="ack-btn"
                  :title="t('incidents.playback_title')"
                  @click.prevent="togglePlayback(item.id)"
                ><MapPin :size="16" /></button>
                <button
                  class="ack-btn"
                  :title="t('incidents.diagnostic_title')"
                  @click.prevent="toggleDiagnostic(item.id)"
                ><Activity :size="16" /></button>
                <button v-if="!item.is_resolved && !item.acked_at" class="ack-btn" :title="t('incidents.acknowledge')" @click.prevent="ack(item)"><CheckCircle :size="16" /></button>
                <button v-else-if="!item.is_resolved && item.acked_at" class="ack-btn ack-btn--active" :title="t('incidents.unacknowledge')" @click.prevent="unack(item)"><CheckCircle :size="16" /></button>
              </span>
            </div>
            <div v-if="hasRunbook(item) && expandedRunbooks[item.id]"
              class="inc-runbook runbook-preview prose prose-invert max-w-none text-sm"
              v-html="renderRunbook(item.runbook_markdown)"
            ></div>
            <div v-if="expandedPlayback[item.id]" class="px-3 py-3 bg-slate-950/40">
              <IncidentPlaybackMap :incident-id="item.id" />
            </div>
            <IncidentDiagnosticPanel
              v-if="expandedDiagnostics[item.id]"
              :incident-id="item.id"
            />
          </div>

        </template>
      </div>
    </div>

  </div>
</template>

<script setup>
import { computed, reactive, ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Activity, AlertCircle, CheckCircle, ChevronDown, Link2, MapPin, X } from 'lucide-vue-next'
import api from '../api/client'
import { incidentUpdatesApi } from '../api/incidentUpdates'
import { useToast } from '../composables/useToast'
import { renderRunbookMarkdown } from '../lib/runbookMarkdown'
import { useFilterPreset } from '../composables/useFilterPreset'
import BulkActionBar from '../components/shared/BulkActionBar.vue'
import IncidentPlaybackMap from '../components/dashboard/IncidentPlaybackMap.vue'
import IncidentDiagnosticPanel from '../components/incidents/IncidentDiagnosticPanel.vue'
import { useTimezone } from '../composables/useTimezone'

const { t, locale } = useI18n()
const { success } = useToast()

const loading = ref(false)
const incidents = ref([])

// Filters — persisted across refreshes and shareable via URL (T1-11).
const { state: filters, reset: resetFilters } = useFilterPreset('incidents', {
  status: 'all',
  days: 30,
  verdict: 'all',
})
// Keep the existing template-bound names rather than refactor the markup.
const statusFilter = computed({
  get: () => filters.status,
  set: (v) => { filters.status = v },
})
const daysFilter = computed({
  get: () => filters.days,
  set: (v) => { filters.days = v },
})
// V2-02-02 — filter by network verdict (service_down vs partitions).
const verdictFilter = computed({
  get: () => filters.verdict,
  set: (v) => { filters.verdict = v },
})
const expandedGroups = reactive({})
const expandedRunbooks = reactive({})
// V2-02-06 — incident-id → bool, toggles inline IncidentPlaybackMap below the row.
const expandedPlayback = reactive({})
function togglePlayback(id) {
  expandedPlayback[id] = !expandedPlayback[id]
}
// V2-01-01 — same pattern for the diagnostic panel.
const expandedDiagnostics = reactive({})
function toggleDiagnostic(id) {
  expandedDiagnostics[id] = !expandedDiagnostics[id]
}

function hasRunbook(inc) {
  return !!(inc.runbook_enabled && inc.runbook_markdown && !inc.is_resolved)
}
function toggleRunbook(id) {
  expandedRunbooks[id] = !expandedRunbooks[id]
}
function renderRunbook(md) {
  return renderRunbookMarkdown(md || '')
}

const statusOpts = computed(() => [
  { value: 'all',      label: t('incidents.filter_all') },
  { value: 'open',     label: t('incidents.filter_open') },
  { value: 'resolved', label: t('incidents.filter_resolved') },
])

const dayOpts = computed(() => [
  { value: 7,  label: t('incidents.last_7d') },
  { value: 30, label: t('incidents.last_30d') },
  { value: 90, label: t('incidents.last_90d') },
])

// V2-02-02 — verdict filter options.
const verdictOpts = computed(() => [
  { value: 'all',                     label: t('incidents.verdict_filter_all'),       title: t('incidents.verdict_filter_all_tip') },
  { value: 'service_down',            label: t('incidents.verdict_service_down'),     title: t('incidents.verdict_service_down_tip') },
  { value: 'network_partition_asn',   label: t('incidents.verdict_partition_asn'),    title: t('incidents.verdict_partition_asn_tip') },
  { value: 'network_partition_geo',   label: t('incidents.verdict_partition_geo'),    title: t('incidents.verdict_partition_geo_tip') },
])

/**
 * Group correlated incidents together, keep standalone ones as-is.
 * Returns a flat list of { type: 'group', ... } and { type: 'incident', ... }.
 * Sorted by earliest started_at of each item/group.
 */
const displayItems = computed(() => {
  const groups = {}
  const standalone = []

  for (const inc of incidents.value) {
    if (inc.group_id) {
      if (!groups[inc.group_id]) {
        groups[inc.group_id] = {
          type: 'group',
          key: `g-${inc.group_id}`,
          group_id: inc.group_id,
          correlation_type: inc.correlation_type,
          root_cause: inc.root_cause_monitor_name,
          monitor_names: inc.group_monitor_names || [],
          incidents: [],
          started_at: inc.started_at,
        }
      }
      groups[inc.group_id].incidents.push(inc)
      // Use earliest started_at for sorting
      if (inc.started_at < groups[inc.group_id].started_at) {
        groups[inc.group_id].started_at = inc.started_at
      }
    } else {
      standalone.push({ ...inc, type: 'incident', key: `i-${inc.id}` })
    }
  }

  const items = [...Object.values(groups), ...standalone]
  items.sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''))

  // V2-02-02 — verdict filter (client-side; network_verdict is on the incident itself,
  // not on the group, so we filter individual incidents within groups too).
  if (verdictFilter.value && verdictFilter.value !== 'all') {
    const want = verdictFilter.value
    return items
      .map((it) => {
        if (it.type === 'group') {
          const matched = it.incidents.filter((i) => i.network_verdict === want)
          return matched.length ? { ...it, incidents: matched } : null
        }
        return it.network_verdict === want ? it : null
      })
      .filter(Boolean)
  }
  return items
})

function toggleGroup(groupId) {
  expandedGroups[groupId] = !expandedGroups[groupId]
}

function correlationLabel(type) {
  const labels = {
    probe: t('incidents.correlation_probe'),
    group: t('incidents.correlation_group'),
    dependency: t('incidents.correlation_dependency'),
  }
  return labels[type] || type || '?'
}

async function load() {
  loading.value = true
  try {
    const params = { days: daysFilter.value, limit: 500 }
    if (statusFilter.value === 'open')     params.resolved = 'false'
    if (statusFilter.value === 'resolved') params.resolved = 'true'
    const { data } = await api.get('/incidents/', { params })
    incidents.value = data
  } catch {
    incidents.value = []
  } finally {
    loading.value = false
  }
}

// verdictFilter is applied client-side — no reload needed when it changes.
watch([statusFilter, daysFilter], load)
onMounted(load)

const { format: tzFormat } = useTimezone()

function formatDate(iso) {
  if (!iso) return '—'
  return tzFormat(iso, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }, locale.value)
}

function formatDuration(inc) {
  if (!inc.is_resolved) return '—'
  const secs = inc.duration_seconds
  if (secs == null) return '—'
  if (secs < 60) return `${secs}s`
  if (secs < 3600) return `${Math.round(secs / 60)}m`
  const h = Math.floor(secs / 3600)
  const m = Math.round((secs % 3600) / 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function badgeClass(inc) {
  if (inc.is_resolved) return 'inc-badge--resolved'
  if (inc.acked_at) return 'inc-badge--acked'
  return 'inc-badge--open'
}

function badgeLabel(inc) {
  if (inc.is_resolved) return t('incidents.resolved')
  if (inc.acked_at) return t('incidents.acknowledged')
  return t('incidents.ongoing')
}

// V2-02-02 — render a small badge next to the status when a network verdict
// is available. inconclusive is rendered as nothing to avoid noise.
function verdictBadge(inc) {
  switch (inc.network_verdict) {
    case 'service_down':           return t('incidents.verdict_short_service_down')
    case 'network_partition_asn':  return t('incidents.verdict_short_partition_asn')
    case 'network_partition_geo':  return t('incidents.verdict_short_partition_geo')
    default: return null
  }
}
function verdictBadgeClass(inc) {
  switch (inc.network_verdict) {
    case 'service_down':           return 'inc-badge--verdict-service'
    case 'network_partition_asn':  return 'inc-badge--verdict-asn'
    case 'network_partition_geo':  return 'inc-badge--verdict-geo'
    default: return ''
  }
}
function verdictTooltip(inc) {
  switch (inc.network_verdict) {
    case 'service_down':           return t('incidents.verdict_service_down_tip')
    case 'network_partition_asn':  return t('incidents.verdict_partition_asn_tip')
    case 'network_partition_geo':  return t('incidents.verdict_partition_geo_tip')
    default: return ''
  }
}

// T1-12 — multi-select + bulk ack
const selectedIds = ref(new Set())
function canSelect(inc) {
  return !inc.is_resolved && !inc.acked_at
}
function toggleSelect(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedIds.value = next
}
function clearSelection() { selectedIds.value = new Set() }
async function bulkAck() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  try {
    const { data } = await incidentUpdatesApi.bulkAck(ids)
    success(t('incidents.bulk_ack_success', { count: data.affected ?? ids.length }))
    // Optimistic local update.
    const now = new Date().toISOString()
    for (const inc of incidents.value) {
      if (ids.includes(inc.id)) inc.acked_at = now
    }
  } catch { /* toast already surfaced by axios interceptor if any */ }
  clearSelection()
}

async function ack(inc) {
  try {
    await incidentUpdatesApi.ack(inc.id)
    inc.acked_at = new Date().toISOString()
    success(t('incidents.ack_success'))
  } catch { /* ignore */ }
}

async function unack(inc) {
  try {
    await incidentUpdatesApi.unack(inc.id)
    inc.acked_at = null
    inc.acked_by_id = null
    success(t('incidents.unack_success'))
  } catch { /* ignore */ }
}
</script>

<style scoped>
.incidents {
  padding: 1.25rem 1rem 2rem;
  max-width: 64rem;
  margin: 0 auto;
}
@media (min-width: 640px)  { .incidents { padding: 1.5rem 1.5rem 2rem; } }
@media (min-width: 1024px) { .incidents { padding: 2rem 2rem 2.5rem; } }

.incidents__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}
.incidents__title {
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -.02em;
  line-height: 1.2;
}
.incidents__sub {
  font-size: .8125rem;
  color: var(--text-3);
  margin-top: .25rem;
}

.incidents__filters {
  display: flex;
  flex-wrap: wrap;
  gap: .5rem;
  margin-bottom: 1rem;
  align-items: center;
  justify-content: space-between;
}

.filter-group { display: flex; gap: 4px; }

.filter-btn {
  padding: 4px 12px;
  border-radius: 6px;
  font-size: .75rem;
  font-weight: 500;
  border: 1px solid var(--border);
  background: none;
  color: var(--text-3);
  cursor: pointer;
  transition: all .15s;
  font-family: inherit;
}
.filter-btn:hover { border-color: var(--border-hover); color: var(--text-2); }
.filter-btn--active {
  background: var(--bg-surface-2);
  border-color: var(--border-hover);
  color: var(--text-1);
}

/* Table rows */
.inc-row {
  display: grid;
  grid-template-columns: 100px 1fr 80px 150px 80px 40px;
  gap: .75rem;
  align-items: center;
  padding: .625rem 1.125rem;
}
@media (max-width: 640px) {
  .inc-row {
    grid-template-columns: auto 1fr 44px;
    gap: .625rem .75rem;
    padding: .875rem 1rem;
    min-height: 64px;
  }
  /* Hide stand-alone type cell — type is shown inline next to the started_at line */
  .inc-col--type { display: none; }
  /* Re-flow the started/duration so they sit on a 2nd line below the monitor name */
  .inc-col--monitor {
    grid-column: 2 / 3;
    grid-row: 1;
    white-space: normal;
  }
  .inc-col--started {
    grid-column: 2 / 3;
    grid-row: 2;
    font-size: .7rem;
    color: var(--text-3);
  }
  .inc-col--duration {
    grid-column: 2 / 3;
    grid-row: 2;
    justify-self: end;
    font-size: .7rem;
    color: var(--text-3);
  }
  .inc-col--status { grid-column: 1 / 2; grid-row: 1 / 3; align-self: center; }
  .inc-col--actions { grid-column: 3 / 4; grid-row: 1 / 3; align-self: center; }
}

.inc-row--head {
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface-2);
}
.inc-row--head .inc-col {
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-3);
}

.inc-row--data {
  border-bottom: 1px solid var(--border);
  text-decoration: none;
  transition: background .15s;
}
.inc-row--data:last-child { border-bottom: none; }
.inc-row--data:hover { background: rgba(255,255,255,.025); }

.inc-row--grouped {
  padding-left: 2.5rem;
  background: rgba(99,102,241,.02);
}
.inc-row--grouped:hover { background: rgba(99,102,241,.05); }

.inc-col { font-size: .8125rem; color: var(--text-2); }
.inc-col--monitor { font-weight: 500; color: var(--text-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-decoration: none; }
.inc-col--type {
  font-size: .6875rem;
  font-family: "JetBrains Mono", monospace;
  color: var(--text-3);
}
.inc-col--duration { font-family: "JetBrains Mono", monospace; font-size: .75rem; }
.inc-col--status { text-decoration: none; }

/* Badges */
.inc-badge {
  display: inline-block;
  font-size: .65rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 99px;
  text-transform: uppercase;
  letter-spacing: .04em;
  white-space: nowrap;
}
.inc-badge--open {
  background: rgba(248,113,113,.12);
  color: #f87171;
  border: 1px solid rgba(248,113,113,.25);
}
.inc-badge--resolved {
  background: rgba(52,211,153,.1);
  color: #34d399;
  border: 1px solid rgba(52,211,153,.2);
}
.inc-badge--acked {
  background: rgba(251,191,36,.1);
  color: #fbbf24;
  border: 1px solid rgba(251,191,36,.25);
}

/* V2-02-02 — network verdict badges (rendered next to the status badge) */
.inc-badge--verdict {
  margin-left: 4px;
  font-size: .58rem;
  letter-spacing: .03em;
  cursor: help;
}
.inc-badge--verdict-service {
  background: rgba(248,113,113,.12);
  color: #f87171;
  border: 1px solid rgba(248,113,113,.25);
}
.inc-badge--verdict-asn {
  background: rgba(96,165,250,.12);
  color: #60a5fa;
  border: 1px solid rgba(96,165,250,.25);
}
.inc-badge--verdict-geo {
  background: rgba(168,85,247,.12);
  color: #a855f7;
  border: 1px solid rgba(168,85,247,.25);
}

/* Ack button */
.ack-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: none;
  color: var(--text-3);
  cursor: pointer;
  transition: all .15s;
}
.ack-btn:hover { border-color: var(--border-hover); color: var(--text-2); }
.ack-btn--active { color: #fbbf24; border-color: rgba(251,191,36,.4); }
@media (max-width: 640px) {
  .ack-btn { width: 44px; height: 44px; -webkit-tap-highlight-color: transparent; }
  .ack-btn svg { width: 20px; height: 20px; }
}

/* ── Correlated group row ─────────────────────────────────────────────────── */
.inc-group {
  border-bottom: 1px solid var(--border);
}

.inc-group__header {
  display: flex;
  align-items: center;
  gap: .75rem;
  width: 100%;
  padding: .75rem 1.125rem;
  background: rgba(99,102,241,.04);
  border: none;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: background .15s;
}
.inc-group__header:hover { background: rgba(99,102,241,.08); }

.inc-group__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: rgba(99,102,241,.15);
  color: #818cf8;
  flex-shrink: 0;
}

.inc-group__summary {
  font-size: .8125rem;
  font-weight: 600;
  color: var(--text-1);
  flex-shrink: 0;
}
.inc-group__cause {
  font-weight: 400;
  color: var(--text-3);
}
.inc-group__cause strong {
  color: #f87171;
  font-weight: 600;
}

.inc-group__type {
  font-size: .65rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 99px;
  text-transform: uppercase;
  letter-spacing: .04em;
  flex-shrink: 0;
}
.inc-group__type--probe { background: rgba(96,165,250,.1); color: #60a5fa; border: 1px solid rgba(96,165,250,.25); }
.inc-group__type--group { background: rgba(168,85,247,.1); color: #a855f7; border: 1px solid rgba(168,85,247,.25); }
.inc-group__type--dependency { background: rgba(251,191,36,.1); color: #fbbf24; border: 1px solid rgba(251,191,36,.25); }

.inc-group__monitors {
  flex: 1;
  font-size: .75rem;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: right;
}

.inc-group__chevron {
  color: var(--text-3);
  flex-shrink: 0;
  transition: transform .2s;
}
.inc-group__chevron--open { transform: rotate(180deg); }

.inc-group__body {
  border-top: 1px solid rgba(99,102,241,.1);
}

.incidents__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3rem 1.5rem;
  gap: .75rem;
  color: var(--text-3);
  font-size: .875rem;
}

.inc-runbook {
  padding: 1rem 1.25rem 1.25rem 3rem;
  border-top: 1px solid rgba(99,102,241,.12);
  background: rgba(99,102,241,.04);
  line-height: 1.55;
}
.inc-runbook :deep(h1),
.inc-runbook :deep(h2),
.inc-runbook :deep(h3) {
  margin: .5rem 0 .35rem;
  color: var(--text-1);
  font-weight: 600;
}
.inc-runbook :deep(h1) { font-size: 1rem; }
.inc-runbook :deep(h2) { font-size: .9375rem; }
.inc-runbook :deep(h3) { font-size: .875rem; }
.inc-runbook :deep(ul),
.inc-runbook :deep(ol) { padding-left: 1.25rem; margin: .25rem 0; }
.inc-runbook :deep(li) { margin: .15rem 0; }
.inc-runbook :deep(code) {
  background: rgba(255,255,255,.08);
  padding: .1em .35em;
  border-radius: 3px;
  font-size: .85em;
}
.inc-runbook :deep(pre) {
  background: rgba(0,0,0,.35);
  padding: .65rem .85rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: .35rem 0;
}
.inc-runbook :deep(a) { color: #60a5fa; text-decoration: underline; }
.inc-runbook :deep(.runbook-task) { list-style: none; margin-left: -1rem; }
.inc-runbook :deep(.runbook-task input[type="checkbox"]) { margin-right: .45rem; }
</style>
