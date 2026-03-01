<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Probes</h1>
        <p class="text-gray-400 mt-1">Remote monitoring agents</p>
      </div>
      <button v-if="auth.isSuperadmin" @click="showRegister = true" class="btn-primary">
        + Register Probe
      </button>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 mb-6 border-b border-gray-800">
      <button
        v-for="tab in tabs" :key="tab"
        @click="activeTab = tab"
        class="px-4 py-2 text-sm font-medium transition-colors"
        :class="activeTab === tab
          ? 'text-blue-400 border-b-2 border-blue-400 -mb-px'
          : 'text-gray-500 hover:text-gray-300'"
      >
        {{ tab }}
      </button>
    </div>

    <!-- ── Liste ── -->
    <div v-if="activeTab === 'Liste'">
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div v-for="probe in probes" :key="probe.id" class="card">
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full" :class="isOnline(probe) ? 'bg-emerald-400' : 'bg-red-500'"></span>
                <h3 class="font-semibold text-white">{{ probe.name }}</h3>
              </div>
              <p class="text-sm text-gray-400 mt-1">{{ probe.location_name }}</p>
            </div>
            <span class="text-xs px-2 py-1 rounded-full"
              :class="isOnline(probe) ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
              {{ isOnline(probe) ? 'Online' : 'Offline' }}
            </span>
          </div>

          <div class="mt-4 space-y-1 text-xs text-gray-500">
            <div v-if="probe.latitude && probe.longitude">
              📍 {{ probe.latitude.toFixed(4) }}, {{ probe.longitude.toFixed(4) }}
            </div>
            <div>
              Last seen: {{ probe.last_seen_at ? formatDate(probe.last_seen_at) : 'Never' }}
            </div>
          </div>

          <div v-if="auth.isSuperadmin" class="mt-4 pt-4 border-t border-gray-800 flex gap-4">
            <button @click="startEdit(probe)" class="text-xs text-blue-400 hover:text-blue-300">
              ✏️ Edit
            </button>
            <button @click="deactivateProbe(probe)" class="text-xs text-red-400 hover:text-red-300">
              Deactivate
            </button>
          </div>
        </div>

        <div v-if="probes.length === 0" class="col-span-full text-center text-gray-500 py-16">
          No probes registered. Install a probe on an external server to start monitoring.
        </div>
      </div>
    </div>

    <!-- ── Carte ── -->
    <div v-if="activeTab === 'Carte'">
      <div ref="mapEl" class="rounded-xl overflow-hidden" style="height: 480px;"></div>

      <!-- Probes sans coordonnées -->
      <div v-if="probesWithoutCoords.length" class="mt-6">
        <h3 class="text-sm font-semibold text-gray-400 mb-3">Sondes non localisées</h3>
        <div class="space-y-2">
          <div v-for="p in probesWithoutCoords" :key="p.id"
            class="flex items-center gap-3 text-sm text-gray-300">
            <span class="w-2 h-2 rounded-full" :class="isOnline(p) ? 'bg-emerald-400' : 'bg-red-500'"></span>
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-gray-500">{{ p.location_name }}</span>
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
        <h2 class="text-lg font-semibold text-amber-400 mb-4">⚠️ Save this API key</h2>
        <p class="text-sm text-gray-300 mb-4">
          This API key will only be shown once. Copy it now and configure your probe with it.
        </p>
        <div class="bg-gray-800 rounded-lg p-3 font-mono text-sm text-white break-all mb-4">
          {{ newApiKey }}
        </div>
        <button @click="newApiKey = null" class="btn-primary w-full">I've copied the key</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { useAuthStore } from '../stores/auth'
import { probesApi } from '../api/probes'
import RegisterProbeModal from '../components/probes/RegisterProbeModal.vue'
import EditProbeModal from '../components/probes/EditProbeModal.vue'

const auth = useAuthStore()
const probes = ref([])
const showRegister = ref(false)
const newApiKey = ref(null)
const editProbe = ref(null)
const tabs = ['Liste', 'Carte']
const activeTab = ref('Liste')
const mapEl = ref(null)

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
function isOnline(probe) {
  if (!probe.last_seen_at) return false
  return (Date.now() - new Date(probe.last_seen_at).getTime()) / 1000 < 120
}

function formatDate(dt) {
  return new Date(dt).toLocaleString('fr-FR')
}

// ── data ─────────────────────────────────────────────────────────────────────
async function loadProbes() {
  try {
    const { data } = await probesApi.list()
    probes.value = data
  } catch {}
}

async function deactivateProbe(probe) {
  if (confirm(`Deactivate probe "${probe.name}"?`)) {
    await probesApi.deactivate(probe.id)
    await loadProbes()
    refreshMap()
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
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${online ? '#34d399' : '#ef4444'};
        border:2px solid ${online ? '#6ee7b7' : '#fca5a5'};
        box-shadow:0 0 6px ${online ? '#34d399' : '#ef4444'}88;
      "></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    })
    const lastSeen = p.last_seen_at ? new Date(p.last_seen_at).toLocaleString('fr-FR') : 'Jamais'
    const marker = L.marker([p.latitude, p.longitude], { icon })
      .addTo(leafletMap)
      .bindPopup(`
        <b>${p.name}</b><br>
        ${p.location_name}<br>
        <span style="color:${online ? '#34d399' : '#ef4444'}">${online ? '● Online' : '● Offline'}</span><br>
        <small>Vu le : ${lastSeen}</small>
      `)
    leafletMarkers.push(marker)
  }
}

async function refreshMap() {
  if (activeTab.value !== 'Carte') return
  if (!leafletMap) {
    await nextTick()
    await initMap()
  } else {
    const L = (await import('leaflet')).default
    renderMarkers(L)
  }
}

// Init map when switching to Carte tab
watch(activeTab, async (tab) => {
  if (tab === 'Carte') {
    await nextTick()
    await initMap()
  }
})

onMounted(loadProbes)
</script>
