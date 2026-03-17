<template>
  <div class="p-8 max-w-6xl mx-auto space-y-6">

    <!-- Header -->
    <div>
      <h1 class="text-2xl font-bold text-gray-100">{{ t('dashboard.title') }}</h1>
      <p class="text-sm text-gray-600 mt-1">Real-time overview of your monitored services</p>
    </div>

    <!-- Summary cards -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <StatCard :label="t('dashboard.total_monitors')" :value="monitors.length"  color="#60a5fa" bg="rgba(59,130,246,.1)"  :icon="Monitor" />
      <StatCard :label="t('dashboard.monitors_up')"    :value="upCount"          color="#34d399" bg="rgba(16,185,129,.1)" :icon="CheckCircle2" />
      <StatCard :label="t('dashboard.monitors_down')"  :value="downCount"        color="#f87171" bg="rgba(239,68,68,.1)"  :icon="XCircle" />
      <StatCard :label="t('dashboard.active_incidents')" :value="incidentCount"  color="#fbbf24" bg="rgba(245,158,11,.1)" :icon="AlertTriangle" />
    </div>

    <!-- Two-column layout on large screens -->
    <div class="grid grid-cols-1 xl:grid-cols-5 gap-6">

      <!-- Monitor list (3/5) -->
      <div class="xl:col-span-3 card p-0 overflow-hidden">
        <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800/80">
          <h2 class="text-sm font-semibold text-gray-100">{{ t('monitors.title') }}</h2>
          <router-link to="/monitors" class="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 transition-colors">
            View all <ArrowRight class="w-3 h-3" />
          </router-link>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="p-5 space-y-3">
          <div v-for="i in 5" :key="i" class="h-12 bg-gray-800/50 rounded-xl animate-pulse" />
        </div>

        <!-- Empty -->
        <div v-else-if="monitors.length === 0" class="flex flex-col items-center py-16 text-center px-6">
          <div class="w-14 h-14 bg-gray-800 rounded-2xl flex items-center justify-center mb-4">
            <Monitor class="w-7 h-7 text-gray-700" />
          </div>
          <p class="text-sm font-medium text-gray-600 mb-1">{{ t('monitors.no_monitors') }}</p>
          <p class="text-xs text-gray-700 mb-5">Add your first URL to start monitoring</p>
          <router-link to="/monitors" class="btn-primary text-sm">
            <Plus class="w-4 h-4" />
            {{ t('monitors.add') }}
          </router-link>
        </div>

        <!-- List -->
        <div v-else class="px-3 py-2">
          <MonitorRow v-for="m in monitors.slice(0, 10)" :key="m.id" :monitor="m" />
          <p v-if="monitors.length > 10" class="text-center text-xs text-gray-700 py-3">
            +{{ monitors.length - 10 }} more —
            <router-link to="/monitors" class="text-blue-400 hover:text-blue-300">view all</router-link>
          </p>
        </div>
      </div>

      <!-- Probe map (2/5) -->
      <div class="xl:col-span-2">
        <ProbeMap />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle, ArrowRight, CheckCircle2, Monitor, Plus, XCircle } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import MonitorRow from '../components/monitors/MonitorRow.vue'
import ProbeMap from '../components/dashboard/ProbeMap.vue'

const StatCard = defineComponent({
  props: { label: String, value: [Number, String], color: String, bg: String, icon: [Object, Function] },
  setup(p) {
    return () => h('div', {
      style: `background:#0a0f1e;border:1px solid #1e293b;border-radius:14px;padding:18px 20px;display:flex;align-items:center;gap:14px;`
    }, [
      h('div', { style: `width:40px;height:40px;border-radius:10px;background:${p.bg};display:flex;align-items:center;justify-content:center;flex-shrink:0;` },
        [h(p.icon, { size: 20, color: p.color, strokeWidth: 2 })]
      ),
      h('div', [
        h('div', { style: `font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;` }, p.label),
        h('div', { style: `font-size:26px;font-weight:700;color:${p.color};line-height:1;` }, String(p.value)),
      ]),
    ])
  },
})

const { t } = useI18n()
const monitorStore = useMonitorStore()
const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

const upCount       = computed(() => monitors.value.filter(m => m._lastStatus === 'up').length)
const downCount     = computed(() => monitors.value.filter(m => ['down', 'error', 'timeout'].includes(m._lastStatus)).length)
const incidentCount = computed(() => monitors.value.filter(m => m._hasOpenIncident).length)

onMounted(() => monitorStore.fetchAll())
</script>
