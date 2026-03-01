<template>
  <div class="p-8" v-if="monitor">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <router-link to="/monitors" class="text-gray-400 hover:text-white text-sm">← Monitors</router-link>
      <div class="flex-1">
        <div class="flex items-center gap-3">
          <span class="w-3 h-3 rounded-full" :class="statusClass"></span>
          <h1 class="text-2xl font-bold text-white">{{ monitor.name }}</h1>
        </div>
        <p class="text-gray-400 text-sm mt-1 font-mono">{{ monitor.url }}</p>
      </div>
    </div>

    <!-- Stats cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-gray-500">Uptime 24h</p>
        <p class="text-2xl font-bold mt-1" :class="uptime24?.uptime_percent >= 99 ? 'text-emerald-400' : 'text-red-400'">
          {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">Uptime 7j</p>
        <p class="text-2xl font-bold mt-1 text-blue-400">
          {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">Réponse moy.</p>
        <p class="text-2xl font-bold mt-1 text-gray-300">
          {{ uptime24?.avg_response_time_ms ? Math.round(uptime24.avg_response_time_ms) + 'ms' : '—' }}
        </p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">p95 réponse</p>
        <p class="text-2xl font-bold mt-1 text-gray-300">
          {{ uptime24?.p95_response_time_ms ? Math.round(uptime24.p95_response_time_ms) + 'ms' : '—' }}
        </p>
      </div>
    </div>

    <!-- SSL card -->
    <div v-if="monitor.ssl_check_enabled && latestSsl" class="card mb-6">
      <div class="flex items-center gap-3 mb-3">
        <ShieldCheck v-if="latestSsl.ssl_valid" class="w-5 h-5 text-emerald-400" />
        <ShieldAlert v-else class="w-5 h-5 text-red-400" />
        <h2 class="text-sm font-semibold text-gray-300">Certificat SSL</h2>
      </div>
      <div class="grid grid-cols-3 gap-4 text-center">
        <div>
          <p class="text-xs text-gray-500 mb-1">Statut</p>
          <span class="text-sm font-semibold px-2 py-0.5 rounded-full"
            :class="latestSsl.ssl_valid ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
            {{ latestSsl.ssl_valid ? 'Valide' : 'Invalide' }}
          </span>
        </div>
        <div>
          <p class="text-xs text-gray-500 mb-1">Expire le</p>
          <p class="text-sm font-mono text-gray-300">
            {{ latestSsl.ssl_expires_at ? formatDateShort(latestSsl.ssl_expires_at) : '—' }}
          </p>
        </div>
        <div>
          <p class="text-xs text-gray-500 mb-1">Jours restants</p>
          <p class="text-sm font-bold"
            :class="latestSsl.ssl_days_remaining > monitor.ssl_expiry_warn_days ? 'text-emerald-400'
                  : latestSsl.ssl_days_remaining > 7 ? 'text-amber-400' : 'text-red-400'">
            {{ latestSsl.ssl_days_remaining ?? '—' }}
          </p>
        </div>
      </div>
    </div>
    <div v-else-if="monitor.ssl_check_enabled && !latestSsl" class="card mb-6">
      <div class="flex items-center gap-2 text-gray-500 text-sm">
        <Shield class="w-4 h-4" />
        SSL check activé — en attente du premier résultat
      </div>
    </div>

    <!-- Availability timeline (30-min buckets, 24h) -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">Disponibilité globale — 24h</h2>
        <span class="text-xs text-gray-500">buckets de 30 min · toutes sondes agrégées</span>
      </div>
      <apexchart
        v-if="availSeries[0]?.data?.length"
        type="bar"
        height="140"
        :options="availOptions"
        :series="availSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">Pas encore de données</p>
    </div>

    <!-- Response time per probe -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">Temps de réponse par sonde — 24h</h2>
        <div class="flex gap-3">
          <span v-for="(s, i) in rtSeries" :key="s.name" class="flex items-center gap-1.5 text-xs text-gray-400">
            <span class="w-3 h-1.5 rounded-full inline-block" :style="`background:${probeColors[i % probeColors.length]}`" />
            {{ s.name }}
          </span>
        </div>
      </div>
      <apexchart
        v-if="rtSeries.length"
        type="line"
        height="220"
        :options="rtOptions"
        :series="rtSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">Pas encore de données</p>
    </div>

    <!-- Recent checks table -->
    <div class="card">
      <h2 class="text-sm font-semibold text-gray-300 mb-4">Checks récents</h2>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 border-b border-gray-800">
            <th class="pb-2 text-left">Heure</th>
            <th class="pb-2 text-left">Sonde</th>
            <th class="pb-2 text-left">Statut</th>
            <th class="pb-2 text-left">HTTP</th>
            <th class="pb-2 text-left">Réponse</th>
            <th class="pb-2 text-left hidden md:table-cell">Redirections</th>
            <th v-if="monitor.ssl_check_enabled" class="pb-2 text-left hidden lg:table-cell">SSL</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-800">
          <tr v-for="r in results.slice(0, 50)" :key="r.id">
            <td class="py-2 text-gray-400 text-xs">{{ formatDate(r.checked_at) }}</td>
            <td class="py-2 text-xs">
              <span class="font-medium" :style="`color:${probeColor(r.probe_id)}`">
                {{ probeName(r.probe_id) }}
              </span>
            </td>
            <td class="py-2">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                :class="r.status === 'up' ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
                {{ r.status }}
              </span>
            </td>
            <td class="py-2 text-gray-300">{{ r.http_status ?? '—' }}</td>
            <td class="py-2 text-gray-300">{{ r.response_time_ms ? Math.round(r.response_time_ms) + 'ms' : '—' }}</td>
            <td class="py-2 text-gray-400 hidden md:table-cell">{{ r.redirect_count }}</td>
            <td v-if="monitor.ssl_check_enabled" class="py-2 hidden lg:table-cell">
              <span v-if="r.ssl_valid === null || r.ssl_valid === undefined" class="text-gray-600 text-xs">—</span>
              <span v-else-if="r.ssl_valid" class="text-xs text-emerald-400">✓ {{ r.ssl_days_remaining }}j</span>
              <span v-else class="text-xs text-red-400">✗ expiré</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
  <div v-else class="p-8 text-gray-400">Chargement…</div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-vue-next'
import { monitorsApi } from '../api/monitors'
import { probesApi } from '../api/probes'

const route = useRoute()
const monitor   = ref(null)
const results   = ref([])
const uptime24  = ref(null)
const uptime7d  = ref(null)
const probeMap  = ref({})   // probeId → { name, location_name }

const probeColors = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#06b6d4']

// ── helpers ──────────────────────────────────────────────────────────────────
const statusMap  = { up: 'bg-emerald-400', down: 'bg-red-500', timeout: 'bg-amber-400', error: 'bg-orange-500' }
const statusClass = computed(() => statusMap[monitor.value?._lastStatus ?? monitor.value?.last_status] || 'bg-gray-600')

const latestSsl = computed(() =>
  results.value.find(r => r.ssl_valid !== null && r.ssl_valid !== undefined) ?? null
)

// Map probe_id → ordered index (stable colors across renders)
const probeIndexMap = computed(() => {
  const ids = [...new Set(results.value.map(r => r.probe_id))]
  return Object.fromEntries(ids.map((id, i) => [id, i]))
})

function probeName(probeId) {
  const p = probeMap.value[probeId]
  return p ? p.location_name : probeId.slice(0, 8) + '…'
}

function probeColor(probeId) {
  const idx = probeIndexMap.value[probeId] ?? 0
  return probeColors[idx % probeColors.length]
}

// ── Chart: response time per probe (line) ────────────────────────────────────
const rtSeries = computed(() => {
  if (!results.value.length) return []
  const byProbe = {}
  for (const r of results.value) {
    if (r.response_time_ms === null) continue
    if (!byProbe[r.probe_id]) byProbe[r.probe_id] = []
    byProbe[r.probe_id].push({ x: new Date(r.checked_at).getTime(), y: Math.round(r.response_time_ms) })
  }
  return Object.entries(byProbe).map(([pid, data], i) => ({
    name: probeName(pid),
    data: data.sort((a, b) => a.x - b.x),
    color: probeColors[i % probeColors.length],
  }))
})

const rtOptions = {
  chart: { type: 'line', toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth', width: 2 },
  xaxis: { type: 'datetime', labels: { style: { colors: '#6b7280' }, datetimeUTC: false } },
  yaxis: { labels: { style: { colors: '#6b7280' }, formatter: v => v + 'ms' } },
  legend: { show: false },
  grid: { borderColor: '#1e293b' },
  theme: { mode: 'dark' },
  tooltip: { x: { format: 'dd/MM HH:mm:ss' }, y: { formatter: v => v + ' ms' } },
}

// ── Chart: aggregated availability (bar, 30-min buckets) ─────────────────────
const BUCKET_MIN = 30

const availSeries = computed(() => {
  if (!results.value.length) return [{ name: 'Disponibilité', data: [] }]

  const now    = Date.now()
  const window = 24 * 60 * 60 * 1000
  const bucket = BUCKET_MIN * 60 * 1000
  const count  = Math.floor(window / bucket)   // 48 buckets

  const buckets = Array.from({ length: count }, (_, i) => ({
    ts:    now - window + (i + 1) * bucket,
    total: 0,
    up:    0,
  }))

  for (const r of results.value) {
    const ts  = new Date(r.checked_at).getTime()
    const idx = Math.floor((ts - (now - window)) / bucket)
    if (idx >= 0 && idx < count) {
      buckets[idx].total++
      if (r.status === 'up') buckets[idx].up++
    }
  }

  return [{
    name: 'Disponibilité',
    data: buckets.map(b => ({
      x: b.ts,
      y: b.total > 0 ? Math.round(b.up / b.total * 100) : null,
    })),
  }]
})

const availOptions = {
  chart: { type: 'bar', toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
  plotOptions: {
    bar: {
      columnWidth: '90%',
      colors: {
        ranges: [
          { from: 0,    to: 49,   color: '#ef4444' },
          { from: 50,   to: 99,   color: '#f59e0b' },
          { from: 99,   to: 100,  color: '#10b981' },
        ],
      },
    },
  },
  dataLabels: { enabled: false },
  xaxis: {
    type: 'datetime',
    labels: { style: { colors: '#6b7280' }, datetimeUTC: false, format: 'HH:mm' },
  },
  yaxis: {
    min: 0, max: 100,
    tickAmount: 4,
    labels: { style: { colors: '#6b7280' }, formatter: v => v + '%' },
  },
  grid: { borderColor: '#1e293b' },
  theme: { mode: 'dark' },
  tooltip: {
    x: { format: 'dd/MM HH:mm' },
    y: { formatter: v => v !== null ? v + '% des sondes UP' : 'Aucune donnée' },
  },
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDate(dt) {
  return new Date(dt).toLocaleString('fr-FR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    day: '2-digit', month: '2-digit',
  })
}

function formatDateShort(dt) {
  return new Date(dt).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

// ── Mount ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
  const id   = route.params.id
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()

  const [monResp, resResp, up24Resp, up7dResp] = await Promise.all([
    monitorsApi.get(id),
    monitorsApi.results(id, { limit: 2000, since }),
    monitorsApi.uptime(id, 24),
    monitorsApi.uptime(id, 168),
  ])
  monitor.value  = monResp.data
  results.value  = resResp.data
  uptime24.value = up24Resp.data
  uptime7d.value = up7dResp.data

  // Fetch probe names (graceful fallback if not superadmin)
  try {
    const { data } = await probesApi.list()
    probeMap.value = Object.fromEntries(data.map(p => [p.id, p]))
  } catch {}
})
</script>
