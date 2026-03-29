<template>
  <div class="dash">

    <!-- Onboarding wizard -->
    <OnboardingWizard
      v-if="showOnboarding"
      @complete="onOnboardingComplete"
    />

    <!-- Normal dashboard -->
    <template v-else>

    <!-- Header -->
    <div class="dash__header">
      <h1 class="dash__title">{{ t('dashboard.title') }}</h1>
      <p class="dash__sub">{{ t('dashboard.subtitle') }}</p>
    </div>

    <!-- Stat cards -->
    <div class="dash__stats">
      <StatCard :label="t('dashboard.total_monitors')" :value="monitors.length"  color="#60a5fa" :bg="'rgba(79,156,249,.1)'"    :icon="Monitor" />
      <StatCard :label="t('dashboard.monitors_up')"    :value="upCount"          color="#34d399" :bg="'rgba(52,211,153,.1)'"    :icon="CheckCircle2" />
      <StatCard :label="t('dashboard.monitors_down')"  :value="downCount"
        :color="downCount > 0 ? '#f87171' : '#34d399'"
        :bg="downCount > 0 ? 'rgba(248,113,113,.1)' : 'rgba(52,211,153,.06)'"
        :icon="XCircle" :pulse="downCount > 0" />
      <StatCard :label="t('dashboard.active_incidents')" :value="incidentCount"  color="#fbbf24" :bg="'rgba(251,191,36,.1)'"    :icon="AlertTriangle" :pulse="incidentCount > 0" />
      <StatCard :label="t('dashboard.global_uptime')"    :value="globalUptimeStr" color="#c084fc" :bg="'rgba(192,132,252,.1)'"   :icon="TrendingUp" />
    </div>

    <!-- Grid -->
    <div class="dash__grid">

      <!-- Monitor list -->
      <div class="card dash__monitors-card p-0 overflow-hidden">
        <div class="dash__card-header">
          <h2 class="dash__card-title">{{ t('monitors.title') }}</h2>
          <router-link to="/monitors" class="dash__view-all">
            {{ t('common.view_all') }} <ArrowRight :size="12" />
          </router-link>
        </div>

        <div v-if="loading" class="p-4 space-y-2">
          <div v-for="i in 5" :key="i" class="skeleton h-12" />
        </div>

        <div v-else-if="monitors.length === 0" class="empty-state">
          <div class="empty-state__icon"><Monitor :size="22" /></div>
          <p class="empty-state__title">{{ t('monitors.no_monitors') }}</p>
          <router-link to="/monitors" class="btn-primary mt-3">
            <Plus :size="14" /> {{ t('monitors.add') }}
          </router-link>
        </div>

        <div v-else class="px-2 py-1.5">
          <MonitorRow v-for="m in previewMonitors" :key="m.id" :monitor="m" />
          <p v-if="monitors.length > 10" class="dash__more-link">
            +{{ monitors.length - 10 }} —
            <router-link to="/monitors">{{ t('common.view_all') }}</router-link>
          </p>
        </div>
      </div>

      <!-- Right column -->
      <div class="dash__right">

        <!-- Active incidents -->
        <div v-if="openIncidents.length > 0" class="card p-0 overflow-hidden">
          <div class="dash__card-header">
            <h2 class="dash__card-title flex items-center gap-2">
              <span class="dot-pulse" />
              {{ t('dashboard.active_incidents') }}
            </h2>
            <span class="dash__incident-count">{{ openIncidents.length }}</span>
          </div>
          <div>
            <div v-for="m in openIncidents.slice(0, 5)" :key="m.id" class="dash__incident-row">
              <span class="dot-down" />
              <router-link :to="`/monitors/${m.id}`" class="dash__incident-name">{{ m.name }}</router-link>
              <span class="dash__incident-type">{{ m.check_type }}</span>
            </div>
          </div>
        </div>

        <!-- Offline probes -->
        <div v-if="offlineProbes.length > 0" class="card p-0 overflow-hidden">
          <div class="dash__card-header">
            <h2 class="dash__card-title flex items-center gap-2">
              <WifiOff :size="13" style="color:#f87171" />
              {{ t('dashboard.offline_probes') }}
            </h2>
            <span class="dash__incident-count">{{ offlineProbes.length }}</span>
          </div>
          <div>
            <router-link
              v-for="p in offlineProbes"
              :key="p.id"
              to="/probes"
              class="dash__incident-row"
            >
              <span class="dot-down" />
              <span class="dash__incident-name">{{ p.name }}</span>
              <span class="dash__incident-type">{{ probeLastSeen(p) }} ago</span>
            </router-link>
          </div>
        </div>

        <!-- Probe map -->
        <ProbeMap />
      </div>
    </div>

    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, ArrowRight, CheckCircle2, Monitor, Plus, TrendingUp, WifiOff, XCircle } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { useAuthStore } from '../stores/auth'
import MonitorRow from '../components/monitors/MonitorRow.vue'
import ProbeMap from '../components/dashboard/ProbeMap.vue'
import OnboardingWizard from '../components/onboarding/OnboardingWizard.vue'
import api from '../api/client'

const STATUS_PRIORITY = { down: 0, error: 1, timeout: 2, up: 3 }

const StatCard = defineComponent({
  props: { label: String, value: [Number, String], color: String, bg: String, icon: [Object, Function], pulse: Boolean },
  setup(p) {
    return () => h('div', { class: 'stat-card' }, [
      h('div', { class: 'stat-card__icon', style: `background:${p.bg};` }, [
        h(p.icon, { size: 18, color: p.color, strokeWidth: 2 }),
        p.pulse ? h('span', { class: 'stat-card__pulse' }) : null,
      ]),
      h('div', { class: 'stat-card__body' }, [
        h('div', { class: 'stat-card__label' }, p.label),
        h('div', { class: 'stat-card__value', style: `color:${p.color};` }, String(p.value)),
      ]),
    ])
  },
})

const { t } = useI18n()
const monitorStore = useMonitorStore()
const auth = useAuthStore()

// Onboarding: show wizard if user hasn't completed it and has no monitors
const showOnboarding = ref(false)

function onOnboardingComplete() {
  showOnboarding.value = false
  monitorStore.fetchAll()
}
const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

const upCount       = computed(() => monitors.value.filter(m => m._lastStatus === 'up').length)
const downCount     = computed(() => monitors.value.filter(m => ['down', 'error', 'timeout'].includes(m._lastStatus)).length)
const incidentCount = computed(() => monitors.value.filter(m => m._hasOpenIncident).length)

const globalUptimeStr = computed(() => {
  const withData = monitors.value.filter(m => m._uptime24h != null)
  if (!withData.length) return '—'
  const avg = withData.reduce((s, m) => s + m._uptime24h, 0) / withData.length
  return avg.toFixed(2) + '%'
})

const previewMonitors = computed(() =>
  [...monitors.value]
    .sort((a, b) => (STATUS_PRIORITY[a._lastStatus] ?? 4) - (STATUS_PRIORITY[b._lastStatus] ?? 4))
    .slice(0, 10)
)

const openIncidents = computed(() => monitors.value.filter(m => m._hasOpenIncident))

// Offline probes
const probes = ref([])
const OFFLINE_MS = 5 * 60 * 1000
const offlineProbes = computed(() =>
  probes.value.filter(p => {
    if (!p.is_enabled) return false
    if (!p.last_seen_at) return true
    return Date.now() - new Date(p.last_seen_at).getTime() > OFFLINE_MS
  })
)
function probeLastSeen(p) {
  if (!p.last_seen_at) return t('common.never')
  const diff = Math.round((Date.now() - new Date(p.last_seen_at).getTime()) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.round(diff / 60)}m`
  return `${Math.round(diff / 3600)}h`
}

onMounted(async () => {
  await monitorStore.fetchAll()

  // Check onboarding status
  if (!auth.user?.onboarding_completed && monitorStore.monitors.length === 0) {
    try {
      const { data } = await api.get('/onboarding/status')
      if (!data.completed && data.monitor_count === 0) {
        showOnboarding.value = true
      }
    } catch {
      // Onboarding endpoint not available — skip wizard
    }
  }

  try {
    const { data } = await api.get('/probes')
    probes.value = data
  } catch {}
})
</script>

<style scoped>
.dash {
  padding: 1.25rem 1rem 2rem;
  max-width: 72rem;
  margin: 0 auto;
}
@media (min-width: 640px)  { .dash { padding: 1.5rem 1.5rem 2rem; } }
@media (min-width: 1024px) { .dash { padding: 2rem 2rem 2.5rem; } }

.dash__header { margin-bottom: 1.5rem; }
.dash__title {
  font-size: 1.375rem;
  font-weight: 700;
  color: var(--text-1);
  letter-spacing: -.02em;
  line-height: 1.2;
}
.dash__sub { font-size: .8125rem; color: var(--text-3); margin-top: .25rem; }

/* Stat cards */
.dash__stats {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: .75rem;
  margin-bottom: 1.5rem;
}
@media (min-width: 640px)  { .dash__stats { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 1024px) { .dash__stats { grid-template-columns: repeat(5, 1fr); } }

/* Main grid */
.dash__grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.25rem;
}
@media (min-width: 1024px) {
  .dash__grid { grid-template-columns: 3fr 2fr; }
}

.dash__right { display: flex; flex-direction: column; gap: 1.25rem; }

/* Card header */
.dash__card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: .875rem 1.125rem;
  border-bottom: 1px solid var(--border);
}
.dash__card-title {
  font-size: .8125rem;
  font-weight: 600;
  color: var(--text-1);
}
.dash__view-all {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: .75rem;
  color: var(--accent);
  transition: color .15s;
  text-decoration: none;
}
.dash__view-all:hover { color: #7cbcff; }

.dash__incident-count {
  font-size: .75rem;
  font-weight: 700;
  color: #f87171;
  background: rgba(248,113,113,.1);
  border: 1px solid rgba(248,113,113,.22);
  border-radius: 99px;
  padding: 2px 8px;
}

/* Empty state */
.dash__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 3rem 1.5rem;
  text-align: center;
}
.dash__empty-icon {
  width: 48px;
  height: 48px;
  background: var(--bg-surface-2);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  margin-bottom: 1rem;
}
.dash__empty-text { font-size: .875rem; color: var(--text-3); }

.dash__more-link {
  text-align: center;
  font-size: .75rem;
  color: var(--text-3);
  padding: .75rem;
}
.dash__more-link a { color: var(--accent); }

/* Incidents */
.dash__incident-row {
  display: flex;
  align-items: center;
  gap: .75rem;
  padding: .625rem 1.125rem;
  border-bottom: 1px solid var(--border);
  transition: background .15s;
}
.dash__incident-row:last-child { border-bottom: none; }
.dash__incident-row:hover { background: rgba(255,255,255,.018); }

.dash__incident-name {
  flex: 1;
  font-size: .8125rem;
  font-weight: 500;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-decoration: none;
  transition: color .15s;
}
.dash__incident-name:hover { color: white; }
.dash__incident-type {
  font-size: .6875rem;
  font-family: "JetBrains Mono", monospace;
  color: var(--text-3);
  flex-shrink: 0;
}

/* Status dots */
.dot-down {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f87171;
  flex-shrink: 0;
}
.dot-pulse {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #f87171;
  flex-shrink: 0;
  animation: pulse-ring 2s ease-out infinite;
}
@keyframes pulse-ring {
  0%   { box-shadow: 0 0 0 0 rgba(248,113,113,.5); }
  70%  { box-shadow: 0 0 0 5px rgba(248,113,113,0); }
  100% { box-shadow: 0 0 0 0 rgba(248,113,113,0); }
}

/* StatCard */
:deep(.stat-card) {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem 1.125rem;
  display: flex;
  align-items: center;
  gap: 12px;
  transition: border-color .2s;
}
:deep(.stat-card:hover) { border-color: var(--border-hover); }

:deep(.stat-card__icon) {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  position: relative;
}
:deep(.stat-card__pulse) {
  position: absolute;
  top: -3px;
  right: -3px;
  width: 8px;
  height: 8px;
  background: #ef4444;
  border-radius: 50%;
  border: 2px solid var(--bg-surface);
  animation: pulse-ring 2s ease-out infinite;
}

:deep(.stat-card__label) {
  font-size: .65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .07em;
  color: var(--text-3);
  margin-bottom: 3px;
  white-space: nowrap;
}
:deep(.stat-card__value) {
  font-size: 1.625rem;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -.03em;
}
</style>
