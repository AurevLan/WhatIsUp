<template>
  <div class="page-body">
    <div class="flex items-center gap-4 mb-6">
      <nav class="breadcrumbs">
        <router-link to="/probes">{{ t('nav.probes') }}</router-link>
        <span class="breadcrumbs__sep">/</span>
        <span class="breadcrumbs__current">{{ t('probeTimeline.title') }}</span>
      </nav>
      <div class="flex-1">
        <h1 class="text-2xl font-bold text-white">
          {{ t('probeTimeline.title') }}
          <span v-if="probe" class="text-blue-400 ml-2">{{ probe.name }}</span>
        </h1>
        <p class="text-gray-400 text-sm mt-1">{{ t('probeTimeline.subtitle') }}</p>
      </div>
      <select v-model="days" @change="load" class="bg-gray-900 border border-gray-700 text-gray-300 text-sm px-3 py-1.5 rounded-lg">
        <option :value="1">1 {{ t('common.day') }}</option>
        <option :value="7">7 {{ t('common.days') }}</option>
        <option :value="14">14 {{ t('common.days') }}</option>
        <option :value="30">30 {{ t('common.days') }}</option>
        <option :value="90">90 {{ t('common.days') }}</option>
      </select>
    </div>

    <div v-if="loading" class="text-gray-400">{{ t('common.loading') }}</div>

    <p v-else-if="timeline.length === 0" class="text-gray-500">
      {{ t('probeTimeline.empty') }}
    </p>

    <div v-else class="space-y-4">
      <div v-for="m in timeline" :key="m.monitor_id" class="card">
        <div class="flex items-center justify-between mb-3">
          <div>
            <router-link
              :to="`/monitors/${m.monitor_id}`"
              class="font-semibold text-white hover:text-blue-400 transition-colors"
            >{{ m.monitor_name }}</router-link>
            <span class="ml-2 text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 uppercase">{{ m.check_type }}</span>
          </div>
          <span class="text-xs text-gray-500 font-mono truncate max-w-xs">{{ m.monitor_url }}</span>
        </div>

        <!-- Incidents timeline bar -->
        <div class="relative h-8 bg-gray-800 rounded overflow-hidden mb-3">
          <div
            v-for="inc in m.incidents" :key="inc.id"
            class="absolute top-0 h-full rounded"
            :class="inc.resolved_at ? 'bg-red-700/70' : 'bg-red-500/90'"
            :style="incidentBarStyle(inc)"
            :title="`${formatDt(inc.started_at)} → ${inc.resolved_at ? formatDt(inc.resolved_at) : 'En cours'} (${inc.scope})`"
          ></div>
        </div>

        <!-- Incident list -->
        <div class="space-y-1">
          <div
            v-for="inc in m.incidents.slice(0, 5)" :key="inc.id + '-row'"
            class="flex items-center gap-4 text-xs text-gray-400"
          >
            <span
              class="w-2 h-2 rounded-full flex-shrink-0"
              :class="inc.resolved_at ? 'bg-red-700' : 'bg-red-400'"
            ></span>
            <span class="text-gray-300 whitespace-nowrap">{{ formatDt(inc.started_at) }}</span>
            <span class="text-gray-600">→</span>
            <span class="whitespace-nowrap">{{ inc.resolved_at ? formatDt(inc.resolved_at) : t('probeTimeline.ongoing') }}</span>
            <span v-if="inc.duration_seconds" class="text-gray-500">{{ formatDuration(inc.duration_seconds) }}</span>
            <span class="px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">{{ inc.scope }}</span>
          </div>
          <p v-if="m.incidents.length > 5" class="text-xs text-gray-600">
            + {{ m.incidents.length - 5 }} {{ t('probeTimeline.more') }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { probesApi } from '../api/probes'

const { t } = useI18n()
const route = useRoute()

const probe = ref(null)
const timeline = ref([])
const loading = ref(true)
const days = ref(7)

// Window boundaries for bar positioning
const windowStart = ref(Date.now())
const windowEnd = ref(Date.now())

function formatDt(iso) {
  return new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function formatDuration(s) {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(1)}h`
}

function incidentBarStyle(inc) {
  const start = new Date(inc.started_at).getTime()
  const end = inc.resolved_at ? new Date(inc.resolved_at).getTime() : Date.now()
  const total = windowEnd.value - windowStart.value
  if (total === 0) return {}
  const left = Math.max(0, (start - windowStart.value) / total) * 100
  const width = Math.max(0.5, (end - start) / total) * 100
  return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
}

async function load() {
  loading.value = true
  const probeId = route.params.id
  const now = Date.now()
  windowEnd.value = now
  windowStart.value = now - days.value * 24 * 60 * 60 * 1000
  try {
    const [timelineRes, probeRes] = await Promise.all([
      probesApi.incidentTimeline(probeId, days.value),
      probesApi.get(probeId),
    ])
    timeline.value = timelineRes.data
    probe.value = probeRes.data
  } catch {
    timeline.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
