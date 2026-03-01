<template>
  <div style="padding:32px;max-width:1100px;margin:0 auto;">

    <!-- Header -->
    <div style="margin-bottom:28px;">
      <h1 style="font-size:22px;font-weight:700;color:#f1f5f9;margin:0 0 4px;">Dashboard</h1>
      <p style="font-size:13px;color:#475569;margin:0;">Real-time overview of your monitored services</p>
    </div>

    <!-- Summary cards -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:28px;">
      <StatCard label="Total Monitors" :value="monitors.length"  color="#60a5fa" bg="rgba(59,130,246,.1)"   :icon="Monitor" />
      <StatCard label="Operational"    :value="upCount"          color="#34d399" bg="rgba(16,185,129,.1)"  :icon="CheckCircle2" />
      <StatCard label="Incidents"      :value="downCount"        color="#f87171" bg="rgba(239,68,68,.1)"   :icon="XCircle" />
      <StatCard label="Open Incidents" :value="incidentCount"    color="#fbbf24" bg="rgba(245,158,11,.1)"  :icon="AlertTriangle" />
    </div>

    <!-- Monitor list -->
    <div style="background:#0a0f1e;border:1px solid #1e293b;border-radius:16px;overflow:hidden;">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:20px 24px;border-bottom:1px solid #1e293b;">
        <h2 style="font-size:15px;font-weight:600;color:#f1f5f9;margin:0;">Monitors</h2>
        <router-link to="/monitors" style="font-size:13px;color:#60a5fa;text-decoration:none;display:flex;align-items:center;gap:4px;">
          View all <ArrowRight :size="13" />
        </router-link>
      </div>

      <!-- Loading skeleton -->
      <div v-if="loading" style="padding:20px 24px;display:flex;flex-direction:column;gap:12px;">
        <div v-for="i in 5" :key="i" style="height:48px;background:#1e293b;border-radius:10px;animation:pulse 1.5s ease infinite;" />
      </div>

      <!-- Empty state -->
      <div v-else-if="monitors.length === 0" style="display:flex;flex-direction:column;align-items:center;padding:64px 24px;text-align:center;">
        <div style="width:56px;height:56px;background:#1e293b;border-radius:16px;display:flex;align-items:center;justify-content:center;margin-bottom:16px;">
          <Monitor :size="28" color="#334155" />
        </div>
        <p style="font-size:14px;font-weight:500;color:#64748b;margin:0 0 6px;">No monitors yet</p>
        <p style="font-size:13px;color:#334155;margin:0 0 20px;">Add your first URL to start monitoring</p>
        <router-link to="/monitors" class="btn-primary" style="text-decoration:none;">
          <Plus :size="14" />
          Add a monitor
        </router-link>
      </div>

      <!-- List -->
      <div v-else style="padding:8px 16px;">
        <MonitorRow v-for="m in monitors.slice(0,10)" :key="m.id" :monitor="m" />
        <p v-if="monitors.length > 10" style="text-align:center;font-size:12px;color:#334155;padding:12px 0 8px;">
          +{{ monitors.length - 10 }} more —
          <router-link to="/monitors" style="color:#60a5fa;">view all</router-link>
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted } from 'vue'
import { AlertTriangle, ArrowRight, CheckCircle2, Monitor, Plus, XCircle } from 'lucide-vue-next'
import { useMonitorStore } from '../stores/monitors'
import MonitorRow from '../components/monitors/MonitorRow.vue'

// Inline StatCard to avoid extra file
const StatCard = defineComponent({
  props: { label: String, value: [Number,String], color: String, bg: String, icon: [Object, Function] },
  setup(p) {
    return () => h('div', {
      style: `background:#0a0f1e;border:1px solid #1e293b;border-radius:14px;padding:18px 20px;display:flex;align-items:center;gap:14px;`
    }, [
      h('div', { style: `width:40px;height:40px;border-radius:10px;background:${p.bg};display:flex;align-items:center;justify-content:center;flex-shrink:0;` },
        [h(p.icon, { size: 20, color: p.color, strokeWidth: 2 })]
      ),
      h('div', [
        h('div', { style: `font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px;` }, p.label),
        h('div', { style: `font-size:26px;font-weight:700;color:${p.color};line-height:1;` }, p.value),
      ])
    ])
  }
})

const monitorStore = useMonitorStore()
const monitors = computed(() => monitorStore.monitors)
const loading  = computed(() => monitorStore.loading)

const upCount       = computed(() => monitors.value.filter(m => m._lastStatus === 'up').length)
const downCount     = computed(() => monitors.value.filter(m => ['down','error','timeout'].includes(m._lastStatus)).length)
const incidentCount = computed(() => monitors.value.filter(m => m._hasOpenIncident).length)

onMounted(() => monitorStore.fetchAll())
</script>

<style>
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
</style>
