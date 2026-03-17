<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('probes.title') }}</h1>
        <p class="text-gray-400 mt-1">{{ t('probes.subtitle') }}</p>
      </div>
      <button v-if="auth.isSuperadmin" @click="showRegister = true" class="btn-primary">
        + {{ t('probes.add') }}
      </button>
    </div>

    <!-- Error banner -->
    <div v-if="errorMsg" class="mb-4 px-4 py-3 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-sm">
      {{ errorMsg }}
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b border-gray-800">
      <button
        v-for="tab in tabs" :key="tab.key"
        @click="activeTab = tab.key"
        class="px-4 py-2 text-sm font-medium transition-colors"
        :class="activeTab === tab.key
          ? 'text-blue-400 border-b-2 border-blue-400 -mb-px'
          : 'text-gray-500 hover:text-gray-300'"
      >
        {{ tab.label }}
      </button>
    </div>

    <!-- ── Liste ── -->
    <div v-if="activeTab === 'list'">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div v-for="probe in probes" :key="probe.id"
          class="card"
          :class="!probe.is_active ? 'opacity-60 border border-gray-700' : ''">
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="w-2 h-2 rounded-full"
                  :class="probeStatusClass(probe)"></span>
                <h3 class="font-semibold text-white">{{ probe.name }}</h3>
                <span v-if="!probe.is_active"
                  class="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">
                  {{ t('probes.inactive') }}
                </span>
                <span :class="probe.network_type === 'internal'
                  ? 'bg-purple-500/15 text-purple-400 border-purple-500/30'
                  : 'bg-blue-500/15 text-blue-400 border-blue-500/30'"
                  class="text-xs px-2 py-0.5 rounded-full border">
                  {{ probe.network_type === 'internal' ? '🏢 ' + t('probes.network_internal_badge') : '🌐 ' + t('probes.network_external_badge') }}
                </span>
              </div>
              <p class="text-sm text-gray-400 mt-1">{{ probe.location_name }}</p>
            </div>
            <span class="text-xs px-2 py-1 rounded-full"
              :class="!probe.is_active
                ? 'bg-gray-800 text-gray-500'
                : isOnline(probe)
                  ? 'bg-emerald-900/50 text-emerald-400'
                  : 'bg-red-900/50 text-red-400'">
              {{ !probe.is_active ? t('probes.inactive') : isOnline(probe) ? t('probes.online') : t('probes.offline') }}
            </span>
          </div>

          <div class="mt-4 space-y-1 text-xs text-gray-500">
            <div v-if="probe.latitude && probe.longitude">
              📍 {{ probe.latitude.toFixed(4) }}, {{ probe.longitude.toFixed(4) }}
            </div>
            <div>
              {{ t('probes.last_seen') }}: {{ probe.last_seen_at ? formatDate(probe.last_seen_at) : t('common.never') }}
            </div>
          </div>

          <div v-if="auth.isSuperadmin" class="mt-4 pt-4 border-t border-gray-800 flex gap-4">
            <router-link
              :to="`/probes/${probe.id}/timeline`"
              class="text-xs text-purple-400 hover:text-purple-300"
            >📊 {{ t('probeTimeline.title') }}</router-link>
            <button @click="startEdit(probe)" class="text-xs text-blue-400 hover:text-blue-300">
              ✏️ {{ t('common.edit') }}
            </button>
            <button v-if="probe.is_active" @click="toggleActive(probe, false)"
              class="text-xs text-amber-400 hover:text-amber-300">
              {{ t('probes.disable') }}
            </button>
            <button v-else @click="toggleActive(probe, true)"
              class="text-xs text-emerald-400 hover:text-emerald-300">
              {{ t('probes.enable') }}
            </button>
            <button @click="removeProbe(probe)"
              class="text-xs text-red-400 hover:text-red-300 ml-auto">
              {{ t('probes.delete') }}
            </button>
          </div>
        </div>

        <div v-if="probes.length === 0" class="col-span-full text-center text-gray-500 py-16">
          {{ t('probes.no_probes') }}
        </div>
      </div>
    </div>

    <!-- ── Carte ── -->
    <div v-if="activeTab === 'map'">
      <div ref="mapEl" class="rounded-xl overflow-hidden" style="height: 480px;"></div>

      <!-- Probes sans coordonnées -->
      <div v-if="probesWithoutCoords.length" class="mt-6">
        <h3 class="text-sm font-semibold text-gray-400 mb-3">{{ t('probes.no_coordinates') }}</h3>
        <div class="space-y-2">
          <div v-for="p in probesWithoutCoords" :key="p.id"
            class="flex items-center gap-3 text-sm text-gray-300">
            <span class="w-2 h-2 rounded-full" :class="isOnline(p) ? 'bg-emerald-400' : 'bg-red-500'"></span>
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-gray-500">{{ p.location_name }}</span>
            <span :class="p.network_type === 'internal'
              ? 'bg-purple-500/15 text-purple-400 border-purple-500/30'
              : 'bg-blue-500/15 text-blue-400 border-blue-500/30'"
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
    <div v-if="newApiKey" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-amber-700 rounded-2xl w-full max-w-md p-6">
        <h2 class="text-lg font-semibold text-amber-400 mb-4">⚠️ {{ t('probes.api_key_warning') }}</h2>
        <p class="text-sm text-gray-300 mb-4">
          {{ t('probes.api_key_copy_hint') }}
        </p>
        <div class="bg-gray-800 rounded-lg p-3 font-mono text-sm text-white break-all mb-4">
          {{ newApiKey }}
        </div>
        <button @click="newApiKey = null" class="btn-primary w-full">{{ t('probes.api_key_saved') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { probesApi } from '../api/probes'
import RegisterProbeModal from '../components/probes/RegisterProbeModal.vue'
import EditProbeModal from '../components/probes/EditProbeModal.vue'

const { t } = useI18n()
const auth = useAuthStore()
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
  return (Date.now() - new Date(probe.last_seen_at).getTime()) / 1000 < 120
}

function probeStatusClass(probe) {
  if (!probe.is_active) return 'bg-gray-500'
  return isOnline(probe) ? 'bg-emerald-400' : 'bg-red-500'
}

function formatDate(dt) {
  return new Date(dt).toLocaleString()
}

// ── data ─────────────────────────────────────────────────────────────────────
function showError(msg) {
  errorMsg.value = msg
  setTimeout(() => { errorMsg.value = null }, 5000)
}

async function loadProbes() {
  try {
    const { data } = await probesApi.list()
    probes.value = data
  } catch (err) {
    showError(t('common.error'))
    console.error(err)
  }
}

async function toggleActive(probe, isActive) {
  const action = isActive ? t('probes.enable') : t('probes.disable')
  if (!confirm(`${action} "${probe.name}" ?`)) return
  try {
    const { data } = await probesApi.setActive(probe.id, isActive)
    const idx = probes.value.findIndex(p => p.id === probe.id)
    if (idx !== -1) probes.value[idx] = data
    refreshMap()
  } catch (err) {
    showError(t('common.error'))
    console.error(err)
  }
}

async function removeProbe(probe) {
  if (!confirm(
    t('probes.confirm_delete', { name: probe.name }) + '\n\n' +
    t('probes.confirm_delete_detail')
  )) return
  try {
    await probesApi.remove(probe.id)
    probes.value = probes.value.filter(p => p.id !== probe.id)
    refreshMap()
  } catch (err) {
    showError(t('common.error'))
    console.error(err)
  }
}

function startEdit(probe) {
  editProbe.value = probe
}

function onUpdated(updated) {
  const idx = probes.value.findIndex(p => p.id === updated.id)
  if (idx !== -1) probes.value[idx] = updated
  editProbe.value = null
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
    const color = inactive ? '#6b7280' : online ? '#34d399' : '#ef4444'
    const border = inactive ? '#9ca3af' : online ? '#6ee7b7' : '#fca5a5'
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${color};
        border:2px solid ${border};
        box-shadow:0 0 6px ${color}88;
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

onMounted(loadProbes)
</script>
