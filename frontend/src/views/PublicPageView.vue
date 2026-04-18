<template>
  <div class="min-h-screen bg-gray-950 p-8" :style="accentStyle">
    <div class="max-w-4xl mx-auto">

      <!-- Erreur de chargement (404 ou réseau) -->
      <div v-if="loadError" class="text-center py-32">
        <p class="text-4xl mb-4">🔍</p>
        <h1 class="text-2xl font-bold text-white mb-2">{{ t('public_page.not_found_title') }}</h1>
        <p class="text-gray-500 text-sm">{{ t('public_page.not_found_desc') }}</p>
      </div>

      <template v-else>

      <!-- Announcement banner -->
      <div v-if="page?.announcement_banner && !bannerDismissed"
        class="mb-6 flex items-start gap-3 rounded-xl border px-5 py-3 text-sm"
        :style="page.accent_color
          ? `background-color: ${page.accent_color}15; border-color: ${page.accent_color}40; color: ${page.accent_color}`
          : ''"
        :class="!page.accent_color ? 'bg-blue-900/30 border-blue-700/40 text-blue-300' : ''">
        <span class="flex-1">{{ page.announcement_banner }}</span>
        <button @click="bannerDismissed = true" class="shrink-0 opacity-60 hover:opacity-100 transition-opacity">&#x2715;</button>
      </div>

      <!-- Header / Statut global -->
      <div class="text-center mb-10">
        <img v-if="page?.public_logo_url || page?.custom_logo_url" :src="page.public_logo_url || page.custom_logo_url" alt="Logo" class="mx-auto mb-4 max-h-16 object-contain" />
        <h1 class="text-3xl font-bold text-white">{{ page?.public_title || page?.name || 'Status Page' }}</h1>
        <p v-if="page?.public_description || page?.description" class="text-gray-400 mt-2">{{ page.public_description || page.description }}</p>

        <!-- Bandeau statut global -->
        <div class="mt-5">
          <div v-if="globalStatus === 'operational'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-emerald-900/40 border text-emerald-300 font-semibold"
            :style="page?.accent_color ? `border-color: ${page.accent_color}80` : ''"
            :class="!page?.accent_color ? 'border-emerald-700/50' : ''">
            <span class="w-2.5 h-2.5 rounded-full" :style="page?.accent_color ? `background-color: ${page.accent_color}` : ''" :class="!page?.accent_color ? 'bg-emerald-400' : ''"></span>
            {{ t('public.all_operational') }}
          </div>
          <div v-else-if="globalStatus === 'degraded'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-amber-900/40 border border-amber-700/50 text-amber-300 font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse"></span>
            {{ t('public.partial_outage') }}
          </div>
          <div v-else-if="globalStatus === 'down'"
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-red-900/40 border border-red-700/50 text-red-300 font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse"></span>
            {{ t('public.major_outage') }}
          </div>
          <div v-else
            class="inline-flex items-center gap-2.5 px-5 py-2.5 rounded-full bg-gray-800/60 border border-gray-700/50 text-gray-400 font-semibold">
            <span class="w-2.5 h-2.5 rounded-full bg-gray-500"></span>
            {{ t('public_page.no_data') }}
          </div>
        </div>
      </div>

      <!-- Composants (moniteurs) -->
      <section class="space-y-4 mb-10">
        <h2 class="text-lg font-semibold text-gray-300 mb-3">{{ t('public.component_status') }}</h2>

        <div v-if="!loading && monitors.length === 0"
          class="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center text-gray-500 text-sm">
          {{ t('public_page.no_monitors') }}
        </div>

        <div v-for="m in monitors" :key="m.id"
          class="bg-gray-900 border border-gray-800 rounded-xl p-5">

          <!-- Ligne principale -->
          <div class="flex items-center justify-between gap-4">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full shrink-0"
                  :class="{
                    'bg-emerald-400': m.current_status === 'up',
                    'bg-red-500 animate-pulse': m.current_status === 'down',
                    'bg-amber-400': m.current_status === 'timeout',
                    'bg-orange-400': m.current_status === 'error',
                    'bg-gray-600': !m.current_status,
                  }"></span>
                <h3 class="font-semibold text-white truncate">{{ m.name }}</h3>
                <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 uppercase shrink-0">
                  {{ m.check_type }}
                </span>
              </div>

              <div class="mt-1.5 text-sm font-mono">
                <template v-if="m.check_type === 'dns'">
                  <span class="text-gray-600">{{ m.dns_record_type || 'A' }} </span>
                  <span v-if="m.current_value" class="text-emerald-400">{{ m.current_value }}</span>
                  <span v-else class="text-gray-600">—</span>
                </template>
                <template v-else-if="m.check_type === 'tcp'">
                  <span class="text-gray-500">{{ formatTcpTarget(m) }}</span>
                </template>
                <template v-else-if="m.check_type === 'scenario'">
                  <span class="text-gray-500">Browser scenario</span>
                </template>
                <template v-else>
                  <span class="text-gray-500 truncate block">{{ m.url?.replace(/^https?:\/\//, '') }}</span>
                </template>
              </div>
            </div>

            <div class="flex items-center gap-2 shrink-0">
              <div class="text-right">
                <p class="text-lg font-bold"
                  :class="m.uptime_24h >= 99 ? 'text-emerald-400' : m.uptime_24h >= 90 ? 'text-amber-400' : 'text-red-400'">
                  {{ m.uptime_24h?.toFixed(2) ?? '—' }}%
                </p>
                <p class="text-xs text-gray-500">{{ t('public.uptime') }} 24h</p>
              </div>
              <button
                @click.stop="copyBadgeUrl(m.name)"
                :title="t('public.copy_badge_url') || 'Copy badge URL'"
                class="p-1.5 rounded-lg text-gray-500 hover:text-indigo-400 hover:bg-gray-800 transition-colors"
              >
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2h-1.528A6 6 0 004 9.528V4z"/>
                  <path fill-rule="evenodd" d="M8 10a4 4 0 00-3.446 6.032l-.5.866a.75.75 0 101.3.75l.5-.866A4 4 0 108 10z" clip-rule="evenodd"/>
                </svg>
              </button>
            </div>
          </div>

          <!-- Métriques supplémentaires -->
          <div class="mt-3 pt-3 border-t border-gray-800/60 flex items-center gap-4 text-xs text-gray-500">
            <template v-if="m.check_type === 'dns'">
              <span v-if="m.last_checked_at">Checked {{ timeAgo(m.last_checked_at) }}</span>
            </template>
            <template v-else>
              <span v-if="m.avg_response_time_ms">Avg. response {{ Math.round(m.avg_response_time_ms) }}ms</span>
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
                  'bg-emerald-500': day.status === 'up',
                  'bg-amber-400': day.status === 'degraded',
                  'bg-red-500': day.status === 'down',
                  'bg-gray-700': day.status === 'no_data',
                }"
                :title="dayTooltip(day)"
              ></div>
            </div>
            <div class="flex justify-between text-xs text-gray-600 mt-1">
              <span>{{ ninetyDaysAgo }}</span>
              <span>{{ uptimeLast90(m) }}% — {{ t('public.history_90d') }}</span>
              <span>{{ t('public.today') }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- Incidents récents (30 jours) -->
      <section v-if="incidents30d.length" class="mb-10">
        <h2 class="text-lg font-semibold text-gray-300 mb-3">{{ t('public.recent_incidents') }}</h2>
        <div class="space-y-3">
          <div v-for="inc in incidents30d" :key="inc.id"
            class="bg-gray-900 border border-gray-800 rounded-xl p-4">

            <div class="flex items-start gap-4">
              <!-- Badge résolu / en cours -->
              <span
                :class="inc.is_resolved
                  ? 'bg-emerald-900/40 text-emerald-400 border-emerald-700/50'
                  : 'bg-red-900/40 text-red-400 border-red-700/50 animate-pulse'"
                class="text-xs font-semibold px-2 py-0.5 rounded border shrink-0 mt-0.5">
                {{ inc.is_resolved ? 'Resolved' : 'Ongoing' }}
              </span>

              <div class="flex-1 min-w-0">
                <p class="text-white font-medium text-sm">{{ inc.monitor_name }}</p>
                <p class="text-gray-500 text-xs mt-0.5">
                  Started: {{ formatDatetime(inc.started_at) }}
                  <template v-if="inc.resolved_at">
                    · Ended: {{ formatDatetime(inc.resolved_at) }}
                  </template>
                </p>
              </div>

              <!-- Durée -->
              <div v-if="inc.duration_minutes != null" class="text-right shrink-0">
                <span class="text-sm font-semibold text-gray-300">{{ formatDuration(inc.duration_minutes) }}</span>
                <p class="text-xs text-gray-600">duration</p>
              </div>

              <!-- Expand updates -->
              <button
                @click="togglePublicUpdates(inc.id)"
                class="text-xs text-blue-400 hover:text-blue-300 shrink-0"
              >
                {{ expandedPublicIncident === inc.id ? '▲ Hide' : '▼ Updates' }}
              </button>
            </div>

            <!-- Incident updates timeline -->
            <div v-if="expandedPublicIncident === inc.id && publicUpdates[inc.id]" class="mt-3 ml-2 border-l-2 border-gray-700 pl-4 space-y-2">
              <div v-if="publicUpdatesLoading[inc.id]" class="text-xs text-gray-500">Loading…</div>
              <div v-else-if="!publicUpdates[inc.id]?.length" class="text-xs text-gray-600 italic">No updates posted yet.</div>
              <div v-for="u in publicUpdates[inc.id]" :key="u.id" class="relative">
                <span class="absolute -left-[21px] top-1 w-3 h-3 rounded-full border-2 border-gray-700"
                  :class="{
                    'bg-amber-400': u.status === 'investigating',
                    'bg-blue-400': u.status === 'identified',
                    'bg-purple-400': u.status === 'monitoring',
                    'bg-emerald-400': u.status === 'resolved',
                  }"
                ></span>
                <p class="text-xs text-gray-400">{{ formatDatetime(u.created_at) }}</p>
                <p class="text-xs font-semibold capitalize mb-0.5"
                  :class="{
                    'text-amber-400': u.status === 'investigating',
                    'text-blue-400': u.status === 'identified',
                    'text-purple-400': u.status === 'monitoring',
                    'text-emerald-400': u.status === 'resolved',
                  }"
                >{{ u.status }}</p>
                <p class="text-sm text-gray-300">{{ u.message }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section v-else-if="!loading" class="mb-10">
        <h2 class="text-lg font-semibold text-gray-300 mb-3">{{ t('public.recent_incidents') }}</h2>
        <div class="bg-gray-900 border border-gray-800 rounded-xl p-5 text-center text-gray-500 text-sm">
          {{ t('public.no_incidents') }}
        </div>
      </section>

      <!-- Abonnement email -->
      <section class="mb-10 bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h2 class="text-lg font-semibold text-gray-300 mb-1">{{ t('public.subscribe') }}</h2>
        <p class="text-gray-500 text-sm mb-4">Receive email notifications for incidents and restorations.</p>

        <form @submit.prevent="subscribe" class="flex gap-3 flex-wrap">
          <input
            v-model="subEmail"
            type="email"
            :placeholder="t('public.subscribe_email')"
            required
            :disabled="subLoading"
            class="flex-1 min-w-48 bg-gray-800 border border-gray-700 rounded-lg px-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
          />
          <button
            type="submit"
            :disabled="subLoading"
            class="px-5 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors disabled:opacity-50">
            {{ subLoading ? 'Loading…' : t('public.subscribe_btn') }}
          </button>
        </form>

        <p v-if="subMessage"
          :class="subError ? 'text-red-400' : 'text-emerald-400'"
          class="mt-3 text-sm">
          {{ subMessage }}
        </p>
      </section>

      <!-- Footer -->
      <div class="text-center text-xs text-gray-600">
        Powered by <span class="text-gray-500">WhatIsUp</span> ·
        Last updated: {{ lastUpdated }}
      </div>

      </template>
    </div>
    <!-- Inject custom CSS from status page settings -->
    <component v-if="page?.public_custom_css" :is="'style'" v-text="page.public_custom_css" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { publicApi } from '../api/public.js'
import { useToast } from '../composables/useToast'

const { t } = useI18n()
const { success: toastSuccess } = useToast()

const route = useRoute()
const page = ref(null)
const monitors = ref([])
const incidents30d = ref([])
const loading = ref(true)
const lastUpdated = ref(new Date().toLocaleTimeString('fr-FR'))

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
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}min ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function formatDatetime(iso) {
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function formatDuration(minutes) {
  if (minutes < 60) return `${minutes}min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m > 0 ? `${h}h${m}min` : `${h}h`
}

function dayTooltip(day) {
  const statusLabel = {
    up: 'Operational',
    degraded: 'Degraded',
    down: 'Outage',
    no_data: 'No data',
  }
  const uptime = day.uptime_pct != null ? ` — ${day.uptime_pct.toFixed(1)}%` : ''
  return `${day.date} · ${statusLabel[day.status] ?? day.status}${uptime}`
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
  const url = `${window.location.origin}/api/v1/public/badge/${slug}/${encodeURIComponent(monitorName)}`
  navigator.clipboard.writeText(url).then(() => {
    toastSuccess('Badge URL copied!')
  })
}

const ninetyDaysAgo = computed(() => {
  const d = new Date()
  d.setDate(d.getDate() - 89)
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit' })
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

onMounted(async () => {
  const slug = route.params.slug
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
    lastUpdated.value = new Date().toLocaleTimeString('fr-FR')
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
        lastUpdated.value = new Date().toLocaleTimeString('fr-FR')
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
