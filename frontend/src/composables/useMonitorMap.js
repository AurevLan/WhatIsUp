// Leaflet map for the "Map" tab — lazy-loaded on first activation.
//
// Markers are colour-coded by probe last_status; clicking one opens a popup
// with the probe name/location/response time. The map instance is recreated
// from scratch each time `loadAndInit` is called when there's no existing
// instance — markers cleared, leaflet re-imported (cached after first call).
//
// All teardown runs in onScopeDispose so callers don't have to remember
// `monitorLeafletMap.remove()` in their own onUnmounted.

import { computed, nextTick, onScopeDispose, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { buildMapPopup } from '../lib/mapPopup'
import { monitorsApi } from '../api/monitors'
import { useTimezone } from './useTimezone'
import { cssVar } from '../lib/themeColors'

export function useMonitorMap(monitorIdRef) {
  const { t, locale } = useI18n()
  const { format: tzFormat } = useTimezone()

  const fmt = (v) =>
    v
      ? tzFormat(
          v,
          { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
          locale.value,
        )
      : ''

  const probeMapEl = ref(null)
  const probeStatuses = ref([]) // list of ProbeMonitorStatus
  let leafletMap = null
  let markers = []

  const probesWithCoords = computed(() =>
    probeStatuses.value.filter((p) => p.latitude != null && p.longitude != null),
  )
  const probesWithoutCoords = computed(() =>
    probeStatuses.value.filter((p) => p.latitude == null || p.longitude == null),
  )

  function markerColor(p) {
    // cssVar lu à l'appel (suit le thème) ; fallback hex pour jsdom
    if (!p.last_status)
      return { dot: 'bg-(--text-3)', text: 'text-(--text-3)', hex: cssVar('--text-3') || '#9a8e76' }
    if (p.last_status === 'up')
      return { dot: 'bg-(--up)', text: 'text-(--up)', hex: cssVar('--up') || '#8fc09e' }
    return { dot: 'bg-(--down)', text: 'text-(--down)', hex: cssVar('--down') || '#e8876b' }
  }

  function statusLabel(p) {
    if (!p.last_status) return t('monitor_detail.no_check_yet')
    return (
      p.last_status +
      (p.response_time_ms ? ` — ${Math.round(p.response_time_ms)}ms` : '')
    )
  }

  async function init() {
    if (!probeMapEl.value) return
    const L = (await import('leaflet')).default
    await import('leaflet/dist/leaflet.css')

    delete L.Icon.Default.prototype._getIconUrl
    L.Icon.Default.mergeOptions({
      iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
      iconUrl: new URL('leaflet/dist/images/marker-icon.png', import.meta.url).href,
      shadowUrl: new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href,
    })

    leafletMap = L.map(probeMapEl.value).setView([20, 0], 2)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(leafletMap)

    markers.forEach((m) => m.remove())
    markers = []

    for (const p of probesWithCoords.value) {
      const col = markerColor(p)
      const icon = L.divIcon({
        className: '',
        html: `<div style="
          width:14px;height:14px;border-radius:50%;
          background:${col.hex};
          border:2px solid ${col.hex}aa;
          box-shadow:0 0 6px ${col.hex}88;
        "></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      })
      const checkedAt = p.last_checked_at ? fmt(p.last_checked_at) : 'Never'
      const marker = L.marker([p.latitude, p.longitude], { icon })
        .addTo(leafletMap)
        // Probe name and location are tenant-supplied: never interpolate them
        // into a popup string (Leaflet renders it as innerHTML).
        .bindPopup(
          buildMapPopup([
            { text: p.name, bold: true, style: 'font-size:13px;' },
            { text: p.location_name, style: 'color:var(--text-3);font-size:11px;' },
            [
              {
                text: `● ${p.last_status ?? t('monitor_detail.no_check_yet')}`,
                style: `color:${col.hex};`,
              },
              p.response_time_ms != null
                ? { text: ` — ${Math.round(p.response_time_ms)}ms` }
                : null,
            ],
            { text: checkedAt, style: 'font-size:11px;color:var(--text-3);' },
          ])
        )
      markers.push(marker)
    }
  }

  async function loadAndInit() {
    if (!probeStatuses.value.length) {
      try {
        const { data } = await monitorsApi.probeStatus(monitorIdRef.value)
        probeStatuses.value = data
      } catch {
        // Silent: map renders empty if probe statuses can't load.
      }
    }
    await nextTick()
    if (!leafletMap) await init()
  }

  onScopeDispose(() => {
    if (leafletMap) {
      leafletMap.remove()
      leafletMap = null
    }
    markers = []
  })

  return {
    probeMapEl,
    probeStatuses,
    probesWithCoords,
    probesWithoutCoords,
    markerColor,
    statusLabel,
    loadAndInit,
  }
}
