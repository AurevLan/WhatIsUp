<template>
  <div class="dash">

    <!-- Onboarding wizard -->
    <OnboardingWizard
      v-if="showOnboarding"
      @complete="onOnboardingComplete"
    />

    <!-- Normal dashboard -->
    <template v-else>

    <!-- Hero -->
    <section class="dash__hero">
      <p class="dash__kicker">{{ todayStr }}</p>
      <h1 class="dash__title font-display" :class="{ 'dash__title--down': !loading && downCount > 0 }">
        <template v-if="loading">{{ t('dashboard.hero_loading') }}<span class="dash__ellip">…</span></template>
        <template v-else-if="downCount === 0">{{ t('dashboard.hero_ok_1') }} <em>{{ t('dashboard.hero_ok_2') }}</em></template>
        <template v-else>{{ t('dashboard.hero_down_pre', downCount) }} <em>{{ t('dashboard.hero_down_em') }}</em></template>
      </h1>
      <p v-if="!loading && monitors.length > 0 && downCount === 0" class="dash__lede">
        {{ t('dashboard.lede_ok', { monitors: monitors.length, probes: probesOnline }) }}
      </p>
      <p v-else-if="!loading && downCount > 0" class="dash__lede dash__lede--warn">
        {{ t('dashboard.lede_down', openIncidents.length) }}
      </p>
    </section>

    <!-- Stat ribbon -->
    <section v-if="monitors.length > 0" class="dash__stats">
      <router-link
        v-for="(s, i) in statCards"
        :key="s.label"
        :to="s.to"
        class="dash__stat"
        :style="{ animationDelay: 80 + i * 90 + 'ms' }"
      >
        <span class="dash__stat-value font-display" :class="s.tone ? `dash__stat-value--${s.tone}` : ''">{{ s.value }}</span>
        <span class="dash__stat-label">{{ s.label }}</span>
      </router-link>
    </section>

    <!-- Loading -->
    <div v-if="loading" class="card p-4 mt-10 space-y-3">
      <SkeletonRow v-for="i in 5" :key="i" />
    </div>

    <!-- Empty state -->
    <EmptyState
      v-else-if="monitors.length === 0"
      :title="t('monitors.no_monitors')"
      :text="t('empty.monitors_text')"
      :cta-label="t('monitors.add')"
      replay-tour
      @cta="$router.push('/monitors')"
    >
      <template #icon><Monitor :size="22" /></template>
    </EmptyState>

    <template v-else>

    <!-- Active incidents -->
    <section v-if="openIncidents.length" class="dash__section">
      <h2 class="dash__h2 font-display">{{ t('dashboard.active_incidents') }}</h2>
      <router-link v-for="m in openIncidents.slice(0, 6)" :key="m.id" :to="`/monitors/${m.id}`" class="dash__incident">
        <span class="dash__incident-pip" aria-hidden="true" />
        <span class="dash__incident-name">{{ m.name }}</span>
        <span class="dash__incident-type">{{ m.check_type }}</span>
        <span class="dash__incident-go" aria-hidden="true">→</span>
      </router-link>
    </section>

    <!-- Offline probes -->
    <section v-if="offlineProbes.length" class="dash__section">
      <h2 class="dash__h2 font-display">{{ t('dashboard.offline_probes') }}</h2>
      <router-link v-for="p in offlineProbes" :key="p.id" to="/probes" class="dash__incident">
        <WifiOff :size="13" class="dash__incident-wifi" aria-hidden="true" />
        <span class="dash__incident-name">{{ p.name }}</span>
        <span class="dash__incident-type">{{ probeLastSeen(p) }}</span>
        <span class="dash__incident-go" aria-hidden="true">→</span>
      </router-link>
    </section>

    <!-- Services -->
    <section class="dash__section">
      <div class="dash__section-head">
        <h2 class="dash__h2 font-display">{{ t('dashboard.services') }}</h2>
        <router-link to="/monitors" class="dash__all">{{ t('common.view_all') }} →</router-link>
      </div>
      <div class="dash__cards">
        <router-link
          v-for="(m, i) in previewMonitors"
          :key="m.id"
          :to="`/monitors/${m.id}`"
          class="dash__card"
          :class="{ 'dash__card--down': isDown(m) }"
          :style="{ animationDelay: Math.min(i * 55, 660) + 'ms' }"
        >
          <div class="dash__card-row">
            <span class="dash__pill" :class="isDown(m) ? 'dash__pill--down' : 'dash__pill--up'">
              {{ isDown(m) ? t('dashboard.pill_down') : t('dashboard.pill_up') }}
            </span>
            <span class="dash__card-ms">{{ m._lastResponseTimeMs != null ? m._lastResponseTimeMs + ' ms' : '' }}</span>
          </div>
          <h3 class="dash__card-name">{{ m.name }}</h3>
          <svg v-if="sparkPath(m._sparkline)" class="dash__spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
            <path :d="sparkPath(m._sparkline) + ' L100,28 L0,28 Z'" class="dash__spark-fill" :class="{ 'dash__spark-fill--down': isDown(m) }" />
            <path :d="sparkPath(m._sparkline)" class="dash__spark-line" :class="{ 'dash__spark-line--down': isDown(m) }" />
          </svg>
          <div class="dash__card-foot">
            <span>{{ m.check_type }}</span>
            <span v-if="m._uptime24h != null">{{ m._uptime24h.toFixed(2) }} % / 24 h</span>
          </div>
        </router-link>
      </div>
      <p v-if="monitors.length > PREVIEW_COUNT" class="dash__more">
        <router-link to="/monitors">+{{ monitors.length - PREVIEW_COUNT }} — {{ t('common.view_all') }}</router-link>
      </p>
    </section>

    <!-- Probe map -->
    <section class="dash__section">
      <h2 class="dash__h2 font-display">{{ t('nav.probes') }}</h2>
      <ProbeMap />
    </section>

    </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Monitor, WifiOff } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import { useAuthStore } from '../stores/auth'
import ProbeMap from '../components/dashboard/ProbeMap.vue'
import OnboardingWizard from '../components/onboarding/OnboardingWizard.vue'
import SkeletonRow from '../components/shared/SkeletonRow.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import { useTour } from '../composables/useTour'
import api from '../api/client'

const STATUS_PRIORITY = { down: 0, error: 1, timeout: 2, up: 3 }
const PREVIEW_COUNT = 12

const { t, locale } = useI18n()
const monitorStore = useMonitorStore()
const auth = useAuthStore()

// Onboarding: show wizard if user hasn't completed it and has no monitors
const showOnboarding = ref(false)
const { shouldStartTour, clearTour } = useTour()

function onOnboardingComplete() {
  showOnboarding.value = false
  monitorStore.fetchAll()
}

const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

function isDown(m) {
  return ['down', 'error', 'timeout'].includes(m._lastStatus)
}

const downCount     = computed(() => monitors.value.filter(m => isDown(m)).length)
const openIncidents = computed(() => monitors.value.filter(m => m._hasOpenIncident))

const previewMonitors = computed(() =>
  [...monitors.value]
    .sort((a, b) => (STATUS_PRIORITY[a._lastStatus] ?? 4) - (STATUS_PRIORITY[b._lastStatus] ?? 4))
    .slice(0, PREVIEW_COUNT)
)

const globalUptime = computed(() => {
  const withData = monitors.value.filter(m => m._uptime24h != null)
  if (!withData.length) return null
  return withData.reduce((s, m) => s + m._uptime24h, 0) / withData.length
})

// Compteurs animés à l'arrivée des données (une seule fois, sautés si
// prefers-reduced-motion ; les updates WS suivants affichent les valeurs réelles)
const animating = ref(false)
const animated = ref({ total: 0, online: 0, trouble: 0 })
const realStats = computed(() => ({
  total: monitors.value.length,
  online: monitors.value.length - downCount.value,
  trouble: downCount.value,
}))
let countersPlayed = false

watch(() => monitors.value.length, (len) => {
  if (!len || countersPlayed) return
  countersPlayed = true
  const reduced = typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced || typeof requestAnimationFrame !== 'function') return
  const target = realStats.value
  animating.value = true
  const t0 = performance.now()
  const DURATION = 650
  const tick = (now) => {
    const p = Math.min((now - t0) / DURATION, 1)
    const e = 1 - (1 - p) ** 3
    animated.value = {
      total: Math.round(target.total * e),
      online: Math.round(target.online * e),
      trouble: Math.round(target.trouble * e),
    }
    if (p < 1) requestAnimationFrame(tick)
    else animating.value = false
  }
  requestAnimationFrame(tick)
})

const shownStats = computed(() => (animating.value ? animated.value : realStats.value))

const statCards = computed(() => [
  { value: shownStats.value.total, label: t('dashboard.stat_services'), to: '/monitors' },
  { value: shownStats.value.online, label: t('dashboard.stat_online'), tone: 'up', to: '/monitors?status=up' },
  { value: shownStats.value.trouble, label: t('dashboard.stat_trouble'), tone: downCount.value > 0 ? 'down' : null, to: '/monitors?status=down' },
  { value: globalUptime.value != null ? globalUptime.value.toFixed(2) + ' %' : '—', label: t('dashboard.stat_uptime'), to: '/incidents' },
])

const todayStr = computed(() =>
  new Date().toLocaleDateString(locale.value === 'fr' ? 'fr-FR' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
)

// Probes
const probes = ref([])
const OFFLINE_MS = 5 * 60 * 1000
const offlineProbes = computed(() =>
  probes.value.filter(p => {
    if (!p.is_active) return false
    if (!p.last_seen_at) return true
    return Date.now() - new Date(p.last_seen_at).getTime() > OFFLINE_MS
  })
)
const probesOnline = computed(() => probes.value.filter(p => p.is_active).length - offlineProbes.value.length)

function probeLastSeen(p) {
  if (!p.last_seen_at) return t('common.never')
  const diff = Math.round((Date.now() - new Date(p.last_seen_at).getTime()) / 1000)
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.round(diff / 60)}m`
  return `${Math.round(diff / 3600)}h`
}

function sparkPath(values) {
  if (!values || values.length < 2) return ''
  const v = values.slice(-30)
  const min = Math.min(...v)
  const max = Math.max(...v)
  const span = max - min || 1
  const pts = v.map((x, i) => [
    (i / (v.length - 1)) * 100,
    26 - ((x - min) / span) * 22,
  ])
  return 'M' + pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' L')
}

onMounted(async () => {
  await monitorStore.fetchAll()

  // Tour replay (T1-18) — user explicitly asked to re-see the wizard
  if (shouldStartTour()) {
    showOnboarding.value = true
    clearTour()
  } else if (!auth.user?.onboarding_completed && monitorStore.monitors.length === 0) {
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
/* ════ Dashboard VELOURS — tout sur tokens : fonctionne en encre et ivoire ════ */
.dash {
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 clamp(16px, 3vw, 32px) 48px;
}

/* Hero */
.dash__hero { padding: clamp(28px, 6vh, 64px) 0 8px; max-width: 820px; }
.dash__kicker {
  margin: 0 0 10px;
  font-size: 12.5px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--text-3);
}
.dash__title {
  margin: 0;
  font-weight: 470;
  font-size: clamp(34px, 5.5vw, 64px);
  line-height: 1.04;
  color: var(--text-1);
  animation: dash-rise .6s cubic-bezier(.2,.7,.2,1) backwards;
}
.dash__title em {
  font-style: italic; font-weight: 520;
  color: var(--up);
  font-variation-settings: "opsz" 100;
  transition: color .3s;
}
.dash__title--down em { color: var(--down); }
.dash__lede {
  margin: 16px 0 0;
  font-size: 15px; color: var(--text-3); max-width: 56ch;
  animation: dash-rise .6s .12s cubic-bezier(.2,.7,.2,1) backwards;
}
.dash__lede--warn { color: var(--down); }
.dash__ellip { animation: dash-pulse 1.2s ease-in-out infinite; }

/* Stat ribbon */
.dash__stats {
  display: flex; flex-wrap: wrap; gap: 14px;
  margin-top: 32px; padding-top: 24px;
  border-top: 1px solid var(--border);
}
.dash__stat {
  flex: 1 1 140px;
  display: flex; flex-direction: column; gap: 2px;
  border-radius: var(--radius-sm); padding: 6px 8px; margin: -6px -8px;
  animation: dash-rise .55s cubic-bezier(.2,.7,.2,1) backwards;
  transition: background .2s;
}
.dash__stat:hover { background: var(--bg-surface-2); }
.dash__stat-value {
  font-size: clamp(24px, 3vw, 36px); font-weight: 560;
  color: var(--text-1);
}
.dash__stat-value--up { color: var(--up); }
.dash__stat-value--down { color: var(--down); }
.dash__stat-label { font-size: 11.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--text-3); }

/* Sections */
.dash__section { margin-top: 40px; }
.dash__section-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.dash__h2 { font-weight: 520; font-size: 21px; margin: 0 0 14px; color: var(--text-1); }
.dash__section-head .dash__h2 { margin-bottom: 0; }
.dash__all { font-size: 13px; color: var(--accent); }
.dash__all:hover { text-decoration: underline; }

/* Incidents / sondes offline */
.dash__incident {
  display: flex; align-items: center; gap: 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 13px 18px; margin-bottom: 10px;
  box-shadow: var(--shadow-card);
  transition: transform .22s cubic-bezier(.2,.7,.2,1), box-shadow .22s;
}
.dash__incident:hover { transform: translateY(-2px); box-shadow: var(--shadow-card-hover); }
.dash__incident-pip {
  width: 9px; height: 9px; border-radius: 99px; flex-shrink: 0;
  background: var(--down);
  animation: dash-pulse 1.6s ease-in-out infinite;
}
.dash__incident-wifi { color: var(--down); flex-shrink: 0; }
.dash__incident-name { font-weight: 600; font-size: 13.5px; color: var(--text-1); }
.dash__incident-type { font-size: 12px; color: var(--text-3); }
.dash__incident-go { margin-left: auto; color: var(--text-3); transition: transform .2s, color .2s; }
.dash__incident:hover .dash__incident-go { transform: translateX(4px); color: var(--text-1); }

/* Services grid */
.dash__cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
.dash__card {
  display: block;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 16px 12px;
  box-shadow: var(--shadow-card);
  transition: transform .24s cubic-bezier(.2,.7,.2,1), box-shadow .24s, border-color .24s;
  animation: dash-rise .5s cubic-bezier(.2,.7,.2,1) backwards;
}
.dash__card:hover { transform: translateY(-3px); box-shadow: var(--shadow-card-hover); border-color: var(--border-hover); }
.dash__card--down { border-color: color-mix(in srgb, var(--down) 45%, transparent); }
.dash__card-row { display: flex; justify-content: space-between; align-items: center; }
.dash__pill {
  font-size: 10px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700;
  padding: 3px 9px; border-radius: 99px;
}
.dash__pill--up { color: var(--up); background: color-mix(in srgb, var(--up) 12%, transparent); }
.dash__pill--down { color: var(--bg-surface); background: var(--down); animation: dash-pulse 1.6s ease-in-out infinite; }
.dash__card-ms { font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
.dash__card-name {
  margin: 9px 0 5px; font-size: 15px; font-weight: 650; letter-spacing: -.01em;
  color: var(--text-1);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.dash__spark { width: 100%; height: 28px; display: block; }
.dash__spark-line { fill: none; stroke: var(--up); stroke-width: 1.6; stroke-linejoin: round; stroke-linecap: round; }
.dash__spark-fill { fill: color-mix(in srgb, var(--up) 10%, transparent); }
.dash__spark-line--down { stroke: var(--down); }
.dash__spark-fill--down { fill: color-mix(in srgb, var(--down) 10%, transparent); }
.dash__card-foot { display: flex; justify-content: space-between; margin-top: 7px; font-size: 11px; color: var(--text-3); }

.dash__more { margin-top: 14px; font-size: 12.5px; }
.dash__more a { color: var(--accent); }
.dash__more a:hover { text-decoration: underline; }

@keyframes dash-rise { from { opacity: 0; transform: translateY(14px); } }
@keyframes dash-pulse { 50% { opacity: .45; } }
</style>
