<template>
  <div class="page-body">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="font-display text-2xl font-bold text-(--text-1)">{{ t('probes.title') }}</h1>
        <p class="text-(--text-2) mt-1">{{ t('probes.subtitle') }}</p>
      </div>
      <button v-if="auth.isSuperadmin" @click="showRegister = true" class="btn-primary">
        + {{ t('probes.add') }}
      </button>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-[color-mix(in_srgb,var(--down)_15%,transparent)] border border-[color-mix(in_srgb,var(--down)_35%,transparent)] text-(--down) text-sm">
      {{ errorMsg }}
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

    <!-- ── Loading skeleton ── -->
    <div v-if="loadingProbes && activeTab === 'list'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="i in 6" :key="i" class="card">
        <div class="flex items-start justify-between">
          <div class="flex-1 space-y-2">
            <div class="skeleton-line w-2/3" />
            <div class="skeleton-line w-1/2" style="height:0.5rem" />
          </div>
          <div class="skeleton-line w-16" style="border-radius:99px" />
        </div>
        <div class="mt-4 space-y-1.5">
          <div class="skeleton-line w-3/4" style="height:0.5rem" />
          <div class="skeleton-line w-1/2" style="height:0.5rem" />
        </div>
      </div>
    </div>

    <!-- ── Liste ── -->
    <div v-else-if="activeTab === 'list'">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div v-for="(probe, idx) in probes" :key="probe.id"
          class="card stagger-item"
          :style="{ animationDelay: idx * 40 + 'ms' }"
          :class="!probe.is_active ? 'opacity-60 border border-(--border)' : ''">
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="w-2 h-2 rounded-full"
                  :class="probeStatusClass(probe)"></span>
                <h2 class="font-semibold text-(--text-1)">{{ probe.name }}</h2>
                <span v-if="!probe.is_active"
                  class="text-xs px-1.5 py-0.5 rounded bg-(--bg-surface-2) text-(--text-2)">
                  {{ t('probes.inactive') }}
                </span>
                <span :class="probe.network_type === 'internal'
                  ? 'bg-(--accent-glow) text-(--accent) border-(--accent-border)'
                  : 'bg-(--accent-glow) text-(--accent) border-(--accent-border)'"
                  class="text-xs px-2 py-0.5 rounded-full border">
                  {{ probe.network_type === 'internal' ? '🏢 ' + t('probes.network_internal_badge') : '🌐 ' + t('probes.network_external_badge') }}
                </span>
                <span v-if="probe.agent_status === 'current' && probe.version"
                  class="text-xs px-2 py-0.5 rounded-full border bg-(--bg-surface-2) text-(--text-2) border-(--border)">
                  v{{ probe.version }}
                </span>
                <span v-else-if="probe.agent_status === 'outdated'"
                  class="text-xs px-2 py-0.5 rounded-full border bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn) border-[color-mix(in_srgb,var(--warn)_35%,transparent)]"
                  :title="t('probes.version_outdated_tooltip', { probe: probe.version, server: APP_VERSION })">
                  ⚠️ v{{ probe.version }} — {{ t('probes.version_outdated') }}
                </span>
                <span v-else-if="probe.agent_status === 'unreported' && probe.last_seen_at"
                  class="text-xs px-2 py-0.5 rounded-full border bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] text-(--warn) border-[color-mix(in_srgb,var(--warn)_35%,transparent)]"
                  :title="t('probes.version_unknown_tooltip')">
                  ⚠️ {{ t('probes.version_unknown') }}
                </span>
              </div>
              <p class="text-sm text-(--text-2) mt-1">{{ probe.location_name }}</p>
            </div>
            <span class="text-xs px-2 py-1 rounded-full"
              :class="!probe.is_active
                ? 'bg-(--bg-surface-2) text-(--text-3)'
                : isOnline(probe)
                  ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)'
                  : 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)'">
              {{ !probe.is_active ? t('probes.inactive') : isOnline(probe) ? t('probes.online') : t('probes.offline') }}
            </span>
          </div>

          <div class="mt-4 space-y-1 text-xs text-(--text-3)">
            <div v-if="probe.latitude && probe.longitude">
              📍 {{ probe.latitude.toFixed(4) }}, {{ probe.longitude.toFixed(4) }}
            </div>
            <div>
              {{ t('probes.last_seen') }}: {{ probe.last_seen_at ? formatDate(probe.last_seen_at) : t('common.never') }}
            </div>
          </div>

          <!-- Health metrics (superadmin, probe online with recent health data) -->
          <div v-if="probe.health && isOnline(probe)" class="mt-3 pt-3 border-t border-(--border)">
            <p class="text-xs font-medium text-(--text-3) mb-2">{{ t('probes.health_title') }}</p>
            <div class="space-y-1.5">
              <div v-for="metric in [
                { label: 'CPU', value: probe.health.cpu_percent },
                { label: 'RAM', value: probe.health.ram_percent },
                { label: 'Disk', value: probe.health.disk_percent },
              ]" :key="metric.label" class="flex items-center gap-2">
                <span class="text-xs text-(--text-3) w-10 shrink-0">{{ metric.label }}</span>
                <div class="flex-1 h-1.5 bg-(--bg-surface-2) rounded-full overflow-hidden">
                  <div class="h-full rounded-full transition-all"
                    :class="healthBarColor(metric.value)"
                    :style="{ width: (metric.value ?? 0) + '%' }"></div>
                </div>
                <span class="text-xs text-(--text-2) w-8 text-right shrink-0">
                  {{ metric.value != null ? metric.value.toFixed(0) + '%' : '—' }}
                </span>
              </div>
              <div class="flex justify-between items-center pt-0.5">
                <span class="text-xs text-(--text-3)">{{ t('probes.health_monitors') }}</span>
                <span class="text-xs text-(--text-2)">
                  {{ probe.health.monitors_active }}
                  <span class="text-(--text-3)">({{ probe.health.checks_running }} {{ t('probes.health_running') }})</span>
                </span>
              </div>
              <div v-if="probe.health.load_avg_1m != null" class="flex justify-between items-center">
                <span class="text-xs text-(--text-3)">{{ t('probes.health_load') }} 1m</span>
                <span class="text-xs" :class="probe.health.load_avg_1m > 2 ? 'text-(--warn)' : 'text-(--text-2)'">
                  {{ probe.health.load_avg_1m.toFixed(2) }}
                </span>
              </div>
            </div>
          </div>

          <div v-if="auth.isSuperadmin" class="mt-4 pt-4 border-t border-(--border) flex gap-4">
            <router-link
              :to="`/probes/${probe.id}/timeline`"
              class="text-xs text-(--accent) hover:text-(--accent)"
            >📊 {{ t('probeTimeline.title') }}</router-link>
            <button @click="startEdit(probe)" class="text-xs text-(--accent) hover:text-(--accent)">
              ✏️ {{ t('common.edit') }}
            </button>
            <button v-if="probe.is_active" @click="toggleActive(probe, false)"
              class="text-xs text-(--warn) hover:text-(--warn)">
              {{ t('probes.disable') }}
            </button>
            <button v-else @click="toggleActive(probe, true)"
              class="text-xs text-(--up) hover:text-(--up)">
              {{ t('probes.enable') }}
            </button>
            <button @click="removeProbe(probe)"
              class="text-xs text-(--down) hover:text-(--down) ml-auto">
              {{ t('probes.delete') }}
            </button>
          </div>
        </div>

        <div v-if="probes.length === 0" class="col-span-full">
          <EmptyState
            :title="t('probes.no_probes')"
            :text="t('empty.probes_text')"
            :cta-label="auth.isSuperadmin ? t('probes.add') : ''"
            doc-href="https://github.com/AurevLan/whatisup#probes"
            @cta="showRegister = true"
          >
            <template #icon><Radio :size="22" /></template>
          </EmptyState>
        </div>
      </div>
    </div>

    <!-- ── Carte ── -->
    <div v-if="activeTab === 'map'">
      <div ref="mapEl" class="rounded-xl overflow-hidden" style="height: 480px;"></div>

      <!-- Probes sans coordonnées -->
      <div v-if="probesWithoutCoords.length" class="mt-6">
        <h2 class="text-sm font-semibold text-(--text-2) mb-3">{{ t('probes.no_coordinates') }}</h2>
        <div class="space-y-2">
          <div v-for="p in probesWithoutCoords" :key="p.id"
            class="flex items-center gap-3 text-sm text-(--text-2)">
            <span class="w-2 h-2 rounded-full" :class="isOnline(p) ? 'bg-(--up)' : 'bg-(--down)'"></span>
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-(--text-3)">{{ p.location_name }}</span>
            <span :class="p.network_type === 'internal'
              ? 'bg-(--accent-glow) text-(--accent) border-(--accent-border)'
              : 'bg-(--accent-glow) text-(--accent) border-(--accent-border)'"
              class="text-xs px-2 py-0.5 rounded-full border">
              {{ p.network_type === 'internal' ? '🏢 ' + t('probes.network_internal_badge') : '🌐 ' + t('probes.network_external_badge') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Register probe modal -->
    <RegisterProbeModal v-if="showRegister" @close="showRegister = false" @registered="onRegistered" />

    <!-- Edit probe modal -->
    <EditProbeModal v-if="editProbe" :probe="editProbe"
      @close="editProbe = null" @updated="onUpdated" />

    <!-- Show API key once -->
    <BaseModal :model-value="!!newApiKey" @close="newApiKey = null">
      <template #header>
        <h2 class="text-lg font-semibold text-(--warn)">⚠️ {{ t('probes.api_key_warning') }}</h2>
      </template>
      <p class="text-sm text-(--text-2) mb-4">
        {{ t('probes.api_key_copy_hint') }}
      </p>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 font-mono text-sm text-(--text-1) break-all">
        {{ newApiKey }}
      </div>
      <template #footer>
        <button @click="newApiKey = null" class="btn-primary flex-1">{{ t('probes.api_key_saved') }}</button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { probesApi } from '../api/probes'
import { cssVar, withAlpha } from '../lib/themeColors'
import { APP_VERSION } from '../lib/appVersion'
import { useToast } from '../composables/useToast'
import { useConfirm } from '../composables/useConfirm'
import { useDateFormat } from '../composables/useDateFormat'
import RegisterProbeModal from '../components/probes/RegisterProbeModal.vue'
import EditProbeModal from '../components/probes/EditProbeModal.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import BaseModal from '../components/BaseModal.vue'
import { Radio } from 'lucide-vue-next'

const { t } = useI18n()
const auth = useAuthStore()
const { success, error: toastError } = useToast()
const { confirm } = useConfirm()
const { formatDate } = useDateFormat()
const loadingProbes = ref(true)
const probes = ref([])
const showRegister = ref(false)
const newApiKey = ref(null)
const editProbe = ref(null)
const errorMsg = ref(null)
const activeTab = ref('list')
const mapEl = ref(null)

const tabs = computed(() => [
  { key: 'list', label: t('probes.tab_list') },
  { key: 'map',  label: t('probes.tab_map') },
])

let leafletMap = null
let leafletMarkers = []

// ── computed ──────────────────────────────────────────────────────────────────
const probesWithCoords = computed(() =>
  probes.value.filter(p => p.latitude != null && p.longitude != null)
)
const probesWithoutCoords = computed(() =>
  probes.value.filter(p => p.latitude == null || p.longitude == null)
)

// ── helpers ───────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function isOnline(probe) {
  if (!probe.is_active || !probe.last_seen_at) return false
  return (Date.now() - new Date(probe.last_seen_at).getTime()) / 1000 < 300
}

function probeStatusClass(probe) {
  if (!probe.is_active) return 'bg-(--text-3)'
  return isOnline(probe) ? 'bg-(--up)' : 'bg-(--down)'
}

function healthBarColor(pct) {
  if (pct == null) return 'bg-(--bg-surface-3)'
  if (pct < 60) return 'bg-(--up)'
  if (pct < 80) return 'bg-(--warn)'
  return 'bg-(--down)'
}

// ── data ─────────────────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = null }, 5000)
}

async function loadProbes() {
  try {
    // Superadmins get enriched stats (uptime 24h + live health); others get basic list
    const { data } = auth.isSuperadmin
      ? await probesApi.stats({ skipErrorToast: true })
      : await probesApi.list({ skipErrorToast: true })
    probes.value = data
  } catch (err) {
    showError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    loadingProbes.value = false
  }
}

async function toggleActive(probe, isActive) {
  const action = isActive ? t('probes.enable') : t('probes.disable')
  const ok = await confirm({ title: `${action} "${probe.name}" ?`, confirmLabel: action, danger: !isActive })
  if (!ok) return
  try {
    const { data } = await probesApi.setActive(probe.id, isActive, { skipErrorToast: true })
    const idx = probes.value.findIndex(p => p.id === probe.id)
    if (idx !== -1) probes.value[idx] = data
    success(t(isActive ? 'probes.toast_enabled' : 'probes.toast_disabled', { name: probe.name }))
    refreshMap()
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  }
}

async function removeProbe(probe) {
  const ok = await confirm({
    title: t('probes.confirm_delete', { name: probe.name }),
    message: t('probes.confirm_delete_detail'),
    confirmLabel: t('probes.delete'),
  })
  if (!ok) return
  try {
    await probesApi.remove(probe.id, { skipErrorToast: true })
    probes.value = probes.value.filter(p => p.id !== probe.id)
    success(t('probes.toast_deleted', { name: probe.name }))
    refreshMap()
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  }
}

function startEdit(probe) {
  editProbe.value = probe
}

function onUpdated(updated) {
  const idx = probes.value.findIndex(p => p.id === updated.id)
  if (idx !== -1) probes.value[idx] = updated
  editProbe.value = null
  success(t('probes.toast_updated'))
  refreshMap()
}

function onRegistered(data) {
  showRegister.value = false
  newApiKey.value = data.api_key
  loadProbes()
}

// ── Leaflet map ───────────────────────────────────────────────────────────────
async function initMap() {
  if (!mapEl.value) return
  const L = (await import('leaflet')).default
  await import('leaflet/dist/leaflet.css')

  // Fix default icon path broken by bundlers
  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
    iconUrl: new URL('leaflet/dist/images/marker-icon.png', import.meta.url).href,
    shadowUrl: new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href,
  })

  leafletMap = L.map(mapEl.value).setView([20, 0], 2)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
  }).addTo(leafletMap)

  renderMarkers(L)
}

function renderMarkers(L) {
  if (!leafletMap) return
  leafletMarkers.forEach(m => m.remove())
  leafletMarkers = []

  for (const p of probesWithCoords.value) {
    const online = isOnline(p)
    const inactive = !p.is_active
    // Couleurs design system lues au rendu des marqueurs (re-render au refresh
    // de l'onglet carte — pas de réactivité au toggle thème exigée).
    // Fallbacks hex pour jsdom (cssVar → '').
    const color = inactive
      ? (cssVar('--text-3') || '#9a8e76')
      : online ? (cssVar('--up') || '#8fc09e') : (cssVar('--down') || '#e8876b')
    const border = withAlpha(color, 0.55)
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${color};
        border:2px solid ${border};
        box-shadow:0 0 6px ${withAlpha(color, 0.53)};
      "></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    })
    const lastSeen = p.last_seen_at ? new Date(p.last_seen_at).toLocaleString() : t('common.never')
    const statusLabel = inactive ? ('● ' + t('probes.inactive')) : online ? ('● ' + t('probes.online')) : ('● ' + t('probes.offline'))
    const networkLabel = p.network_type === 'internal'
      ? '🏢 ' + t('probes.network_internal_badge')
      : '🌐 ' + t('probes.network_external_badge')
    const marker = L.marker([p.latitude, p.longitude], { icon })
      .addTo(leafletMap)
      .bindPopup(`
        <b>${escapeHtml(p.name)}</b><br>
        ${escapeHtml(p.location_name)}<br>
        ${escapeHtml(networkLabel)}<br>
        <span style="color:${color}">${statusLabel}</span><br>
        <small>${escapeHtml(t('probes.last_seen'))} : ${escapeHtml(lastSeen)}</small>
      `)
    leafletMarkers.push(marker)
  }
}

async function refreshMap() {
  if (activeTab.value !== 'map') return
  if (!leafletMap) {
    await nextTick()
    await initMap()
  } else {
    const L = (await import('leaflet')).default
    renderMarkers(L)
  }
}

// Init map when switching to map tab
watch(activeTab, async (tab) => {
  if (tab === 'map') {
    await nextTick()
    await initMap()
  }
})

let refreshTimer = null

onMounted(() => {
  loadProbes()
  refreshTimer = setInterval(loadProbes, 60_000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>
