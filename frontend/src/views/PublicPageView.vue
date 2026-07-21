<template>
  <div class="min-h-screen bg-(--bg-base) p-8" :style="accentStyle">
    <div class="max-w-4xl mx-auto">

      <!-- Erreur de chargement (404 ou réseau) -->
      <div v-if="loadError" class="text-center py-32">
        <p class="text-4xl mb-4">🔍</p>
        <h1 class="font-display text-2xl font-bold text-(--text-1) mb-2">{{ t('public_page.not_found_title') }}</h1>
        <p class="text-(--text-3) text-sm">{{ t('public_page.not_found_desc') }}</p>
      </div>

      <template v-else>

      <!-- Announcement banner -->
      <div v-if="page?.announcement_banner && !bannerDismissed"
        class="mb-6 flex items-start gap-3 rounded-xl border px-5 py-3 text-sm"
        :style="page.accent_color
          ? `background-color: ${page.accent_color}15; border-color: ${page.accent_color}40; color: ${page.accent_color}`
          : ''"
        :class="!page.accent_color ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)' : ''">
        <span class="flex-1">{{ page.announcement_banner }}</span>
        <button @click="bannerDismissed = true" class="shrink-0 opacity-60 hover:opacity-100 transition-opacity">&#x2715;</button>
      </div>

      <!-- Header / Statut global -->
      <div class="text-center mb-10">
        <img v-if="page?.public_logo_url || page?.custom_logo_url" :src="page.public_logo_url || page.custom_logo_url" :alt="t('sweep.logo_alt')" class="mx-auto mb-4 max-h-16 object-contain" />
        <h1 class="font-display text-3xl font-bold text-(--text-1)">{{ page?.public_title || page?.name || 'Status Page' }}</h1>
        <p v-if="page?.public_description || page?.description" class="text-(--text-2) mt-2">{{ page.public_description || page.description }}</p>

        <!-- Bandeau statut global -->
        <div class="mt-5">
          <div v-if="globalStatus === 'operational'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-[color-mix(in_srgb,var(--up)_15%,transparent)] border text-(--up) font-semibold"
            :style="page?.accent_color ? `border-color: ${page.accent_color}80` : ''"
            :class="!page?.accent_color ? 'border-[color-mix(in_srgb,var(--up)_35%,transparent)]' : ''">
            <span class="w-2.5 h-2.5 rounded-full" :style="page?.accent_color ? `background-color: ${page.accent_color}` : ''" :class="!page?.accent_color ? 'bg-(--up)' : ''"></span>
            {{ t('public.all_operational') }}
          </div>
          <div v-else-if="globalStatus === 'degraded'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] border border-[color-mix(in_srgb,var(--warn)_35%,transparent)] text-(--warn) font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-(--warn) animate-pulse"></span>
            {{ t('public.partial_outage') }}
          </div>
          <div v-else-if="globalStatus === 'down'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-[color-mix(in_srgb,var(--down)_15%,transparent)] border border-[color-mix(in_srgb,var(--down)_35%,transparent)] text-(--down) font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-(--down) animate-pulse"></span>
            {{ t('public.major_outage') }}
          </div>
          <div v-else
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-(--bg-surface-2) border border-(--border) text-(--text-2) font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-(--text-3)"></span>
            {{ t('public_page.no_data') }}
          </div>
        </div>
      </div>

      <!-- Composants (moniteurs) -->
      <section class="space-y-4 mb-10">
        <h2 class="text-lg font-semibold text-(--text-2) mb-3">{{ t('public.component_status') }}</h2>

        <div v-if="!loading && monitors.length === 0"
          class="bg-(--bg-surface) border border-(--border) rounded-xl p-8 text-center text-(--text-3) text-sm">
          {{ t('public_page.no_monitors') }}
        </div>

        <div v-for="m in monitors" :key="m.id"
          class="bg-(--bg-surface) border border-(--border) rounded-xl p-5">

          <!-- Ligne principale -->
          <div class="flex items-center justify-between gap-4">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full shrink-0"
                  :class="{
                    'bg-(--up)': m.current_status === 'up',
                    'bg-(--down) animate-pulse': m.current_status === 'down',
                    'bg-(--warn)': m.current_status === 'timeout' || m.current_status === 'error',
                    'bg-(--text-3)': !m.current_status,
                  }"></span>
                <h3 class="font-semibold text-(--text-1) truncate">{{ m.name }}</h3>
                <span class="text-xs px-1.5 py-0.5 rounded bg-(--bg-surface-2) text-(--text-3) uppercase shrink-0">
                  {{ m.check_type }}
                </span>
              </div>

              <div class="mt-1.5 text-sm font-mono">
                <template v-if="m.check_type === 'dns'">
                  <span class="text-(--text-3)">{{ m.dns_record_type || 'A' }} </span>
                  <span v-if="m.current_value" class="text-(--up)">{{ m.current_value }}</span>
                  <span v-else class="text-(--text-3)">—</span>
                </template>
                <template v-else-if="m.check_type === 'tcp'">
                  <span class="text-(--text-3)">{{ formatTcpTarget(m) }}</span>
                </template>
                <template v-else-if="m.check_type === 'scenario'">
                  <span class="text-(--text-3)">{{ t('sweep.browser_scenario') }}</span>
                </template>
                <template v-else>
                  <span class="text-(--text-3) truncate block">{{ m.url?.replace(/^https?:\/\//, '') }}</span>
                </template>
              </div>
            </div>

            <div class="flex items-center gap-2 shrink-0">
              <div class="text-right">
                <p class="font-display text-lg font-bold"
                  :class="m.uptime_24h >= 99 ? 'text-(--up)' : m.uptime_24h >= 90 ? 'text-(--warn)' : 'text-(--down)'">
                  {{ m.uptime_24h?.toFixed(2) ?? '—' }}%
                </p>
                <p class="text-xs text-(--text-3)">{{ t('public.uptime') }} 24h</p>
              </div>
              <button
                @click.stop="copyBadgeUrl(m.name)"
                :title="t('public.copy_badge_url') || 'Copy badge URL'"
                :aria-label="t('public.copy_badge_url') || 'Copy badge URL'"
                class="p-1.5 rounded-lg text-(--text-3) hover:text-(--accent) hover:bg-(--bg-surface-2) transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2h-1.528A6 6 0 004 9.528V4z" />
                  <path fill-rule="evenodd" d="M8 10a4 4 0 00-3.446 6.032l-.5.866a.75.75 0 101.3.75l.5-.866A4 4 0 108 10z" clip-rule="evenodd" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Métriques supplémentaires -->
          <div class="mt-3 pt-3 border-t border-(--border) flex items-center gap-4 text-xs text-(--text-3)">
            <template v-if="m.check_type === 'dns'">
              <span v-if="m.last_checked_at">{{ t('public.checked_ago', { ago: timeAgo(m.last_checked_at) }) }}</span>
            </template>
            <template v-else>
              <span v-if="m.avg_response_time_ms">{{ t('public.avg_response_ms', { ms: Math.round(m.avg_response_time_ms) }) }}</span>
            </template>
          </div>

          <!-- Historique 90 jours -->
          <div v-if="m.history_90d?.length" class="mt-4">
            <div class="flex items-end gap-px h-8 overflow-hidden">
              <div
                v-for="(day, idx) in m.history_90d"
                :key="idx"
                class="flex-1 h-8 rounded-sm cursor-pointer transition-opacity hover:opacity-75 relative group"
                :class="{
                  'bg-(--up)': day.status === 'up',
                  'bg-(--warn)': day.status === 'degraded',
                  'bg-(--down)': day.status === 'down',
                  'bg-(--bg-surface-2)': day.status === 'no_data',
                }"
                :title="dayTooltip(day)"
              ></div>
            </div>
            <div class="flex justify-between text-xs text-(--text-3) mt-1">
              <span>{{ ninetyDaysAgo }}</span>
              <span>{{ uptimeLast90(m) }}% — {{ t('public.history_90d') }}</span>
              <span>{{ t('public.today') }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Incidents récents (30 jours) -->
      <section v-if="incidents30d.length" class="mb-10">
        <h2 class="text-lg font-semibold text-(--text-2) mb-3">{{ t('public.recent_incidents') }}</h2>
        <div class="space-y-3">
          <div v-for="inc in incidents30d" :key="inc.id"
            class="bg-(--bg-surface) border border-(--border) rounded-xl p-4">

            <div class="flex items-start gap-4">
              <!-- Badge résolu / en cours -->
              <span
                :class="inc.is_resolved
                  ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up) border-[color-mix(in_srgb,var(--up)_35%,transparent)]'
                  : 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down) border-[color-mix(in_srgb,var(--down)_35%,transparent)] animate-pulse'"
                class="text-xs font-semibold px-2 py-0.5 rounded border shrink-0 mt-0.5">
                {{ inc.is_resolved ? t('public.resolved') : t('public.ongoing') }}
              </span>

              <div class="flex-1 min-w-0">
                <p class="text-(--text-1) font-medium text-sm">{{ inc.monitor_name }}</p>
                <p class="text-(--text-3) text-xs mt-0.5">
                  {{ t('public.started') }}: {{ formatDatetime(inc.started_at) }}
                  <template v-if="inc.resolved_at">
                    · {{ t('public.ended') }}: {{ formatDatetime(inc.resolved_at) }}
                  </template>
                </p>
              </div>

              <!-- Durée -->
              <div v-if="inc.duration_minutes != null" class="text-right shrink-0">
                <span class="text-sm font-semibold text-(--text-2)">{{ formatDurationMinutes(inc.duration_minutes) }}</span>
                <p class="text-xs text-(--text-3)">{{ t('public.duration') }}</p>
              </div>

              <!-- Expand updates -->
              <button
                @click="togglePublicUpdates(inc.id)"
                class="text-xs text-(--accent) hover:text-(--accent) shrink-0"
              >
                {{ expandedPublicIncident === inc.id ? t('public.hide_updates') : t('public.show_updates') }}
              </button>
            </div>

            <!-- Incident updates timeline -->
            <div v-if="expandedPublicIncident === inc.id && publicUpdates[inc.id]" class="mt-3 ml-2 border-l-2 border-(--border) pl-4 space-y-2">
              <div v-if="publicUpdatesLoading[inc.id]" class="text-xs text-(--text-3)">{{ t('common.loading') }}</div>
              <div v-else-if="!publicUpdates[inc.id]?.length" class="text-xs text-(--text-3) italic">{{ t('public.no_updates_posted') }}</div>
              <div v-for="u in publicUpdates[inc.id]" :key="u.id" class="relative">
                <span class="absolute -left-[21px] top-1 w-3 h-3 rounded-full border-2 border-(--border)"
                  :class="{
                    'bg-(--warn)': u.status === 'investigating',
                    'bg-(--accent)': u.status === 'identified' || u.status === 'monitoring',
                    'bg-(--up)': u.status === 'resolved',
                  }"
                ></span>
                <p class="text-xs text-(--text-2)">{{ formatDatetime(u.created_at) }}</p>
                <p class="text-xs font-semibold capitalize mb-0.5"
                  :class="{
                    'text-(--warn)': u.status === 'investigating',
                    'text-(--accent)': u.status === 'identified' || u.status === 'monitoring',
                    'text-(--up)': u.status === 'resolved',
                  }"
                >{{ u.status }}</p>
                <p class="text-sm text-(--text-2)">{{ u.message }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="!loading" class="mb-10">
        <h2 class="text-lg font-semibold text-(--text-2) mb-3">{{ t('public.recent_incidents') }}</h2>
        <div class="bg-(--bg-surface) border border-(--border) rounded-xl p-5 text-center text-(--text-3) text-sm">
          {{ t('public.no_incidents') }}
        </div>
      </section>

      <!-- Abonnement email -->
      <section class="mb-10 bg-(--bg-surface) border border-(--border) rounded-xl p-6">
        <h2 class="text-lg font-semibold text-(--text-2) mb-1">{{ t('public.subscribe') }}</h2>
        <p class="text-(--text-3) text-sm mb-4">{{ t('public.subscribe_desc') }}</p>

        <form @submit.prevent="subscribe" class="flex gap-3 flex-wrap">
          <input
            v-model="subEmail"
            type="email"
            :placeholder="t('public.subscribe_email')"
            required
            :disabled="subLoading"
            class="flex-1 min-w-48 bg-(--bg-surface-2) border border-(--border) rounded-lg px-4 py-2 text-sm text-(--text-1) placeholder-(--text-3) focus:outline-none focus:ring-2 focus:ring-(color:--accent) disabled:opacity-50"
          />
          <button
            type="submit"
            :disabled="subLoading"
            class="px-5 py-2 rounded-lg bg-(--accent-glow) border border-(--accent-border) text-(--accent) hover:bg-[color-mix(in_srgb,var(--accent)_24%,transparent)] text-sm font-medium transition-colors disabled:opacity-50">
            {{ subLoading ? t('common.loading') : t('public.subscribe_btn') }}
          </button>
        </form>

        <p v-if="subMessage"
          :class="subError ? 'text-(--down)' : 'text-(--up)'"
          class="mt-3 text-sm">
          {{ subMessage }}
        </p>
      </section>

      <!-- Footer -->
      <div class="text-center text-xs text-(--text-3)">
        Powered by <span class="text-(--text-3)">WhatIsUp</span> ·
        {{ t('public.last_updated') }}: {{ lastUpdated }}
      </div>

      </template>
    </div>
    <component v-if="page?.public_custom_css" :is="'style'" v-text="page.public_custom_css" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { publicApi } from '../api/public.js'
import { getServerUrl } from '../lib/serverConfig.js'
import { useToast } from '../composables/useToast'
import { useDateFormat } from '../composables/useDateFormat'

const { t } = useI18n()
const { success: toastSuccess } = useToast()
const { formatDate, formatDurationMinutes, intlLocale } = useDateFormat()

const route = useRoute()
const page = ref(null)
const monitors = ref([])
const incidents30d = ref([])
const loading = ref(true)
const nowTime = () => new Date().toLocaleTimeString(intlLocale.value)
const lastUpdated = ref(nowTime())

const loadError = ref(false)
const bannerDismissed = ref(false)

const accentStyle = computed(() => {
  const color = page.value?.public_accent_color || page.value?.accent_color
  if (color) {
    return { '--status-accent': color }
  }
  return {}
})

// Incident updates (public)
const expandedPublicIncident = ref(null)
const publicUpdates = ref({})
const publicUpdatesLoading = ref({})

async function togglePublicUpdates(incidentId) {
  if (expandedPublicIncident.value === incidentId) {
    expandedPublicIncident.value = null
    return
  }
  expandedPublicIncident.value = incidentId
  if (publicUpdates.value[incidentId]) return // already loaded
  publicUpdatesLoading.value[incidentId] = true
  try {
    const slug = route.params.slug
    const { data } = await publicApi.getIncidentUpdates(slug, incidentId)
    publicUpdates.value[incidentId] = data
  } catch {
    publicUpdates.value[incidentId] = []
  } finally {
    publicUpdatesLoading.value[incidentId] = false
  }
}

// Abonnement
const subEmail = ref('')
const subLoading = ref(false)
const subMessage = ref('')
const subError = ref(false)

// ────────────────────────────────────────────────
// Statut global
// ────────────────────────────────────────────────
const globalStatus = computed(() => {
  if (!monitors.value.length) return 'no_data'
  const statuses = monitors.value.map(m => m.current_status)
  if (statuses.some(s => s === 'down')) return 'down'
  if (statuses.some(s => s === 'timeout' || s === 'error')) return 'degraded'
  if (statuses.every(s => s === 'up')) return 'operational'
  return 'no_data'
})

// ────────────────────────────────────────────────
// Formatage
// ────────────────────────────────────────────────
function formatTcpTarget(m) {
  try {
    const u = new URL(m.url)
    return `${u.hostname}:${m.tcp_port || u.port || 80}`
  } catch {
    return m.url
  }
}

function timeAgo(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000)
  if (diff < 60) return t('common.relative_seconds_ago', { n: diff })
  if (diff < 3600) return t('common.relative_minutes_ago', { n: Math.floor(diff / 60) })
  return t('common.relative_hours_ago', { n: Math.floor(diff / 3600) })
}

const formatDatetime = (iso) =>
  formatDate(iso, {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })

function dayTooltip(day) {
  const known = ['up', 'degraded', 'down', 'no_data']
  const label = known.includes(day.status) ? t(`public.day_status_${day.status}`) : day.status
  const uptime = day.uptime_pct != null ? ` — ${day.uptime_pct.toFixed(1)}%` : ''
  return `${day.date} · ${label}${uptime}`
}

function uptimeLast90(monitor) {
  const days = monitor.history_90d ?? []
  const withData = days.filter(d => d.status !== 'no_data')
  if (!withData.length) return '—'
  const avg = withData.reduce((sum, d) => sum + (d.uptime_pct ?? 0), 0) / withData.length
  return avg.toFixed(2)
}

function copyBadgeUrl(monitorName) {
  const slug = route.params.slug
  const origin = getServerUrl() || window.location.origin
  const url = `${origin}/api/v1/public/badge/${slug}/${encodeURIComponent(monitorName)}`
  navigator.clipboard.writeText(url).then(() => {
    toastSuccess(t('public.badge_copied'))
  })
}

const ninetyDaysAgo = computed(() => {
  const d = new Date()
  d.setDate(d.getDate() - 89)
  return d.toLocaleDateString(intlLocale.value, { day: '2-digit', month: '2-digit' })
})

// ────────────────────────────────────────────────
// Abonnement
// ────────────────────────────────────────────────
async function subscribe() {
  subLoading.value = true
  subMessage.value = ''
  subError.value = false
  try {
    const slug = route.params.slug
    await publicApi.subscribe(slug, subEmail.value)
    subMessage.value = t('public.subscribed')
    subEmail.value = ''
  } catch (err) {
    subError.value = true
    subMessage.value = err.response?.data?.detail ?? t('common.error')
  } finally {
    subLoading.value = false
  }
}

// ────────────────────────────────────────────────
// Chargement initial
// ────────────────────────────────────────────────
let publicWs = null

// Les e-mails de confirmation et de désinscription pointent vers cette page
// avec un jeton en query : le routeur n'expose que `/status/:slug`, une
// sous-route serait avalée par le catch-all.
async function handleEmailLinkTokens(slug) {
  const { confirm, unsubscribe } = route.query
  if (!confirm && !unsubscribe) return
  subMessage.value = ''
  subError.value = false
  try {
    if (confirm) {
      await publicApi.confirm(slug, confirm)
      subMessage.value = t('public.subscription_confirmed')
    } else {
      await publicApi.unsubscribe(slug, unsubscribe)
      subMessage.value = t('public.unsubscribed')
    }
  } catch {
    subError.value = true
    subMessage.value = t('public.link_invalid')
  }
}

onMounted(async () => {
  const slug = route.params.slug
  await handleEmailLinkTokens(slug)
  try {
    const [pageResp, monResp, statusResp] = await Promise.all([
      publicApi.getPage(slug),
      publicApi.getMonitors(slug),
      publicApi.getStatus(slug),
    ])
    page.value = pageResp.data
    monitors.value = monResp.data
    incidents30d.value = statusResp.data.incidents_30d ?? []
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
    lastUpdated.value = nowTime()
  }

  // Mise à jour temps réel via WebSocket (public endpoint)
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  publicWs = new WebSocket(`${protocol}//${window.location.host}/ws/public/${slug}`)
  publicWs.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'check_result') {
        const mon = monitors.value.find(m => m.id === data.monitor_id)
        if (mon && data.status) {
          mon.current_status = data.status
          mon.last_checked_at = data.checked_at ?? mon.last_checked_at
        }
        lastUpdated.value = nowTime()
      }
    } catch {
      // ignore parse errors
    }
  }
})

onUnmounted(() => {
  if (publicWs) {
    publicWs.close()
    publicWs = null
  }
})
</script>
