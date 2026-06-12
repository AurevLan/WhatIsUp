<template>
  <div class="card p-0 overflow-hidden">
    <!-- Header -->
    <div class="flex items-center justify-between px-5 py-3 border-b border-(--border)">
      <div class="flex items-center gap-2">
        <Play v-if="!playback.playing.value" class="w-4 h-4 text-(--accent)" />
        <Pause v-else class="w-4 h-4 text-(--accent)" />
        <h3 class="text-sm font-semibold text-(--text-1)">
          {{ t('incidents.playback_title') }}
        </h3>
      </div>
      <div class="text-[11px] text-(--text-3) font-mono">
        {{ playback.cursorAt.value ? cursorLabel : '—' }}
      </div>
    </div>

    <div v-if="playback.loading.value" class="p-6 text-center text-xs text-(--text-3)">
      <div class="animate-pulse">{{ t('common.loading') }}</div>
    </div>

    <div v-else-if="playback.error.value" class="p-6 text-center text-xs text-(--down)">
      {{ playback.error.value }}
    </div>

    <template v-else-if="playback.timeline.value">
      <!-- Map -->
      <div ref="mapEl" style="height: 280px;" class="w-full" />

      <!-- Controls -->
      <div class="flex items-center gap-3 px-5 py-3 border-t border-(--border)">
        <button
          type="button"
          class="rounded-md bg-(--bg-surface-2) hover:bg-(--bg-surface-3) text-(--text-1) px-2.5 py-1 text-xs flex items-center gap-1"
          @click="playback.playing.value ? playback.pause() : playback.play()"
        >
          <component :is="playback.playing.value ? Pause : Play" class="w-3 h-3" />
          {{ playback.playing.value ? t('incidents.playback_pause') : t('incidents.playback_play') }}
        </button>
        <button
          type="button"
          class="rounded-md bg-(--bg-surface-2) hover:bg-(--bg-surface-3) text-(--text-2) px-2 py-1 text-xs"
          @click="playback.reset()"
        >{{ t('incidents.playback_reset') }}</button>
        <input
          type="range"
          min="0"
          :max="playback.durationMs.value"
          :value="playback.cursorMs.value"
          step="100"
          class="flex-1"
          @input="playback.seek(Number($event.target.value))"
        />
        <span class="text-[10px] text-(--text-3) font-mono whitespace-nowrap">
          {{ formatElapsed(playback.cursorMs.value) }} / {{ formatElapsed(playback.durationMs.value) }}
        </span>
      </div>
    </template>

    <div v-else class="p-6 text-center text-xs text-(--text-3)">
      {{ t('incidents.playback_empty') }}
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pause, Play } from 'lucide-vue-next'
import { useIncidentPlayback } from '../../composables/useIncidentPlayback'
import { colorForAsn } from '../../lib/asnPalette'
import { cssVar, withAlpha } from '../../lib/themeColors'

const props = defineProps({
  incidentId: { type: String, required: true },
})

const { t, locale } = useI18n()
const playback = useIncidentPlayback(props.incidentId)
const mapEl = ref(null)

let leafletMap = null
let leafletMarkers = []
let L = null

const cursorLabel = computed(() => {
  if (!playback.cursorAt.value) return ''
  return playback.cursorAt.value.toLocaleString(locale.value, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
})

function formatElapsed(ms) {
  if (ms == null) return '0:00'
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

// Couleurs lues au moment du rendu de chaque frame (pas de réactivité au
// toggle thème exigée : chaque seek/play re-rend les marqueurs). Fallbacks hex
// requis pour jsdom (cssVar → '').
function statusFill(status) {
  switch (status) {
    case 'up': return cssVar('--up') || '#8fc09e'
    case 'down': return cssVar('--down') || '#e8876b'
    case 'timeout':
    case 'error': return cssVar('--warn') || '#dcab4a'
    default: return cssVar('--text-3') || '#9a8e76'
  }
}

async function initMap() {
  if (!mapEl.value || leafletMap) return
  L = (await import('leaflet')).default
  await import('leaflet/dist/leaflet.css')
  leafletMap = L.map(mapEl.value, { zoomControl: true, attributionControl: false })
    .setView([20, 10], 2)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
  }).addTo(leafletMap)
  // Filtre de tuiles en CSS (classe velours-map-tiles) pour varier selon data-theme.
  leafletMap.getContainer().classList.add('velours-map-tiles')
  renderFrame()
}

function renderFrame() {
  if (!leafletMap || !L) return
  for (const m of leafletMarkers) m.remove()
  leafletMarkers = []
  const state = playback.stateAtCursor.value
  if (!state.size) return

  const latlngs = []
  for (const point of state.values()) {
    if (point.probe_lat == null || point.probe_lng == null) continue
    const fill = statusFill(point.status)
    const ring = colorForAsn(point.probe_asn)
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:18px;height:18px;border-radius:50%;
        background:${fill};
        border:3px solid ${ring};
        box-shadow:0 0 8px ${withAlpha(fill, 0.8)};
        transform:translate(-50%,-50%);
      "></div>`,
      iconSize: [0, 0],
      iconAnchor: [0, 0],
    })
    const marker = L.marker([point.probe_lat, point.probe_lng], { icon }).addTo(leafletMap)
    marker.bindTooltip(
      `<b>${point.probe_name || point.probe_id}</b><br>` +
      `<span style="font-size:11px;color:${fill};">${point.status.toUpperCase()}</span>` +
      (point.probe_asn ? `<br><span style="font-family:monospace;font-size:10px;color:${ring};">AS${point.probe_asn}</span>` : ''),
      { className: 'probe-popup', sticky: true }
    )
    leafletMarkers.push(marker)
    latlngs.push([point.probe_lat, point.probe_lng])
  }
  if (latlngs.length > 0 && !leafletMap._fittedOnce) {
    leafletMap.fitBounds(latlngs, { padding: [40, 40], maxZoom: 6 })
    leafletMap._fittedOnce = true
  }
}

watch(playback.stateAtCursor, renderFrame)
watch(() => playback.timeline.value, async (val) => {
  if (val) {
    await initMap()
    renderFrame()
  }
})

onMounted(async () => {
  await playback.load()
})

onUnmounted(() => {
  playback.pause()
  if (leafletMap) {
    leafletMap.remove()
    leafletMap = null
  }
})
</script>

<style>
/* VELOURS — fond de carte assourdi et réchauffé en thème sombre (tuiles
   uniquement, les marqueurs gardent les couleurs du design system).
   Dupliqué depuis ProbeMap.vue : les deux cartes peuvent être chargées
   indépendamment (code-splitting). */
.velours-map-tiles .leaflet-tile-pane {
  filter: brightness(.85) sepia(.25) hue-rotate(-10deg) saturate(.85);
}
:root[data-theme="light"] .velours-map-tiles .leaflet-tile-pane {
  filter: none;
}
</style>
