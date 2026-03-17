<template>
  <div class="card p-0 overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800/80">
      <div class="flex items-center gap-2">
        <Radio class="w-4 h-4 text-blue-400" />
        <h2 class="text-sm font-semibold text-gray-100">Sondes</h2>
        <span class="text-xs text-gray-600 font-mono">({{ probes.length }})</span>
      </div>
      <div class="flex items-center gap-3 text-xs text-gray-600">
        <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-emerald-400 inline-block"/>≥ 99 %</span>
        <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-amber-400 inline-block"/>≥ 90 %</span>
        <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-red-500 inline-block"/>< 90 %</span>
        <span class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-gray-600 inline-block"/>No data</span>
      </div>
    </div>

    <!-- Map -->
    <div ref="mapEl" style="height: 280px;" class="w-full" />

    <!-- Probe list (all probes, compact) -->
    <div class="border-t border-gray-800/80 divide-y divide-gray-800/60">
      <div v-if="loading" class="p-4 flex gap-3">
        <div v-for="i in 2" :key="i" class="h-9 flex-1 rounded-lg bg-gray-800/50 animate-pulse" />
      </div>
      <div v-else-if="probes.length === 0" class="py-6 text-center text-xs text-gray-600">
        Aucune sonde enregistrée.
      </div>
      <template v-else>
        <div v-for="probe in probes" :key="probe.id"
          class="flex items-center gap-3 px-5 py-2.5 hover:bg-white/[.02] transition-colors">
          <!-- Status dot -->
          <span class="w-2 h-2 rounded-full flex-shrink-0" :class="dotClass(probe)" />

          <!-- Name + location -->
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-200 truncate">{{ probe.name }}</p>
            <p class="text-xs text-gray-600 truncate">{{ probe.location_name }}</p>
          </div>

          <!-- Network badge -->
          <span class="text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0"
            :class="probe.network_type === 'internal'
              ? 'bg-purple-500/10 text-purple-400 border-purple-500/20'
              : 'bg-blue-500/10 text-blue-400 border-blue-500/20'">
            {{ probe.network_type === 'internal' ? 'Interne' : 'Externe' }}
          </span>

          <!-- Uptime -->
          <div class="text-right flex-shrink-0 w-16">
            <p class="text-sm font-bold" :class="uptimeColorClass(probe.uptime_24h)">
              {{ probe.uptime_24h != null ? probe.uptime_24h.toFixed(1) + '%' : '—' }}
            </p>
            <p class="text-[10px] text-gray-600">
              {{ probe.check_count_24h > 0 ? probe.check_count_24h + ' checks' : 'no data' }}
            </p>
          </div>

          <!-- Online indicator -->
          <span class="text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0"
            :class="isOnline(probe)
              ? 'bg-emerald-900/40 text-emerald-400'
              : probe.is_active ? 'bg-red-900/30 text-red-400' : 'bg-gray-800 text-gray-500'">
            {{ !probe.is_active ? 'inactive' : isOnline(probe) ? 'online' : 'offline' }}
          </span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { Radio } from 'lucide-vue-next'
import { probesApi } from '../../api/probes'

const probes  = ref([])
const loading = ref(true)
const mapEl   = ref(null)

let leafletMap     = null
let leafletMarkers = []

// ── helpers ───────────────────────────────────────────────────────────────────
function isOnline(probe) {
  if (!probe.is_active || !probe.last_seen_at) return false
  return (Date.now() - new Date(probe.last_seen_at).getTime()) / 1000 < 120
}

function dotClass(probe) {
  if (!probe.is_active) return 'bg-gray-600'
  const u = probe.uptime_24h
  if (!isOnline(probe))  return 'bg-gray-500'
  if (u == null)         return 'bg-gray-500'
  if (u >= 99)           return 'bg-emerald-400'
  if (u >= 90)           return 'bg-amber-400'
  return 'bg-red-500'
}

function uptimeColorClass(u) {
  if (u == null) return 'text-gray-500'
  if (u >= 99)   return 'text-emerald-400'
  if (u >= 90)   return 'text-amber-400'
  return 'text-red-400'
}

function markerColor(probe) {
  if (!probe.is_active)      return { fill: '#6b7280', glow: '' }
  const u = probe.uptime_24h
  if (u == null)             return { fill: '#6b7280', glow: '' }
  if (u >= 99)               return { fill: '#34d399', glow: 'rgba(52,211,153,.5)' }
  if (u >= 90)               return { fill: '#fbbf24', glow: 'rgba(251,191,36,.5)' }
  return                            { fill: '#ef4444', glow: 'rgba(239,68,68,.5)' }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

// ── data ──────────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const { data } = await probesApi.stats()
    probes.value = data
  } finally {
    loading.value = false
  }
}

// ── Leaflet ───────────────────────────────────────────────────────────────────
async function initMap() {
  if (!mapEl.value) return
  const L = (await import('leaflet')).default
  await import('leaflet/dist/leaflet.css')

  if (leafletMap) {
    leafletMap.remove()
    leafletMap = null
    leafletMarkers = []
  }

  leafletMap = L.map(mapEl.value, { zoomControl: true, attributionControl: false })
    .setView([20, 10], 2)

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
  }).addTo(leafletMap)

  // Dark overlay to match the theme
  leafletMap.getContainer().style.filter = 'brightness(.85) saturate(.6) hue-rotate(200deg)'

  renderMarkers(L)
}

function renderMarkers(L) {
  if (!leafletMap) return
  leafletMarkers.forEach(m => m.remove())
  leafletMarkers = []

  const withCoords = probes.value.filter(p => p.latitude != null && p.longitude != null)
  for (const p of withCoords) {
    const { fill, glow } = markerColor(p)
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${fill};border:2px solid ${fill === '#6b7280' ? '#9ca3af' : fill};
        ${glow ? `box-shadow:0 0 8px ${glow};` : ''}
        transform:translate(-50%,-50%);
      "></div>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    })

    const uptime = p.uptime_24h != null ? p.uptime_24h.toFixed(1) + '%' : 'No data'
    const checks = p.check_count_24h > 0 ? `${p.check_count_24h} checks / 24h` : 'no data'
    const online = !p.is_active ? 'inactive' : isOnline(p) ? '● online' : '● offline'

    const marker = L.marker([p.latitude, p.longitude], { icon })
      .addTo(leafletMap)
      .bindPopup(`
        <div style="font-family:system-ui;min-width:140px;">
          <b style="font-size:13px;">${escapeHtml(p.name)}</b><br>
          <span style="color:#94a3b8;font-size:11px;">${escapeHtml(p.location_name)}</span><br>
          <hr style="border-color:#334155;margin:6px 0;">
          <span style="font-size:12px;font-weight:700;color:${fill};">Uptime 24h: ${escapeHtml(uptime)}</span><br>
          <span style="font-size:11px;color:#64748b;">${escapeHtml(checks)}</span><br>
          <span style="font-size:11px;color:#64748b;">${escapeHtml(online)}</span>
        </div>
      `, { className: 'probe-popup' })
    leafletMarkers.push(marker)
  }
}

// Reload every 60s
let timer = null

onMounted(async () => {
  await load()
  await initMap()
  timer = setInterval(async () => {
    await load()
    if (leafletMap) {
      const L = (await import('leaflet')).default
      renderMarkers(L)
    }
  }, 60_000)
})

onUnmounted(() => {
  clearInterval(timer)
  if (leafletMap) { leafletMap.remove(); leafletMap = null }
})

watch(probes, async () => {
  if (leafletMap) {
    const L = (await import('leaflet')).default
    renderMarkers(L)
  }
})
</script>

<style>
.probe-popup .leaflet-popup-content-wrapper {
  background: #0f172a;
  border: 1px solid #1e293b;
  border-radius: 8px;
  color: #e2e8f0;
  box-shadow: 0 4px 24px rgba(0,0,0,.6);
}
.probe-popup .leaflet-popup-tip {
  background: #1e293b;
}
</style>
