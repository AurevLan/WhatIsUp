<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-bold text-white">{{ t('incidentGroups.title') }}</h1>
        <p class="text-gray-400 text-sm mt-1">{{ t('incidentGroups.subtitle') }}</p>
      </div>
      <div class="flex gap-2">
        <button
          v-for="s in ['all', 'open', 'resolved']" :key="s"
          @click="statusFilter = s"
          class="px-3 py-1.5 text-sm rounded-lg border transition-colors"
          :class="statusFilter === s
            ? 'bg-blue-600 border-blue-500 text-white'
            : 'border-gray-700 text-gray-400 hover:border-gray-500'"
        >
          {{ s === 'all' ? 'All' : s === 'open' ? t('incidentGroups.status_open') : t('incidentGroups.status_resolved') }}
        </button>
      </div>
    </div>

    <div v-if="loading" class="text-gray-400">{{ t('common.loading') }}</div>

    <p v-else-if="groups.length === 0" class="text-gray-500">{{ t('incidentGroups.empty') }}</p>

    <div v-else class="space-y-4">
      <div
        v-for="group in groups"
        :key="group.id"
        class="card"
      >
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <span
              class="px-2 py-0.5 text-xs font-semibold rounded-full"
              :class="group.status === 'open'
                ? 'bg-red-900/60 text-red-300'
                : 'bg-emerald-900/60 text-emerald-300'"
            >
              {{ group.status === 'open' ? t('incidentGroups.status_open') : t('incidentGroups.status_resolved') }}
            </span>
            <span class="text-xs text-gray-500 font-mono">{{ group.id }}</span>
          </div>
          <span class="text-xs text-gray-500">
            {{ t('incidentGroups.triggered_at') }}: {{ formatDt(group.triggered_at) }}
            <span v-if="group.resolved_at">
              · {{ t('incidentGroups.resolved_at') }}: {{ formatDt(group.resolved_at) }}
            </span>
          </span>
        </div>

        <!-- Root cause + correlation type -->
        <div v-if="group.root_cause_monitor_name || group.correlation_type" class="flex items-center gap-3 mb-3 text-xs">
          <span v-if="group.root_cause_monitor_name" class="flex items-center gap-1.5">
            <span class="text-gray-500">{{ t('incidentGroups.root_cause') }}:</span>
            <router-link
              :to="`/monitors/${group.root_cause_monitor_id}`"
              class="text-red-400 font-semibold hover:text-red-300"
            >{{ group.root_cause_monitor_name }}</router-link>
          </span>
          <span v-if="group.correlation_type"
            class="px-2 py-0.5 rounded-full text-xs font-medium"
            :class="{
              'bg-blue-900/50 text-blue-300': group.correlation_type === 'probe',
              'bg-purple-900/50 text-purple-300': group.correlation_type === 'group',
              'bg-amber-900/50 text-amber-300': group.correlation_type === 'dependency',
              'bg-cyan-900/50 text-cyan-300': group.correlation_type === 'pattern',
            }"
          >{{ t('incidentGroups.type_' + group.correlation_type) }}</span>
        </div>

        <div class="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p class="text-gray-500 text-xs mb-1">{{ t('incidentGroups.cause_probes') }}</p>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="pid in group.cause_probe_ids" :key="pid"
                class="px-2 py-0.5 bg-gray-800 text-gray-300 text-xs rounded font-mono"
              >{{ probeName(pid) }}</span>
              <span v-if="group.cause_probe_ids.length === 0" class="text-gray-600">—</span>
            </div>
          </div>
          <div>
            <p class="text-gray-500 text-xs mb-1">{{ t('incidentGroups.incidents') }}</p>
            <div class="flex flex-wrap gap-1">
              <router-link
                v-for="ref in group.incident_refs" :key="ref.id"
                :to="`/monitors/${ref.monitor_id}`"
                class="px-2 py-0.5 bg-gray-800 text-blue-400 text-xs rounded font-mono hover:bg-gray-700"
              >{{ String(ref.id).slice(0, 8) }}…</router-link>
              <span v-if="group.incident_refs.length === 0" class="text-gray-600">—</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { incidentGroupsApi } from '../api/incidentGroups'
import { probesApi } from '../api/probes'

const { t } = useI18n()

const groups = ref([])
const loading = ref(true)
const statusFilter = ref('all')
const probeMap = ref({})

function formatDt(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

function probeName(pid) {
  return probeMap.value[pid]?.name ?? pid.slice(0, 8)
}


async function load() {
  loading.value = true
  try {
    const params = statusFilter.value !== 'all' ? { status: statusFilter.value } : {}
    const { data } = await incidentGroupsApi.list(params)
    groups.value = data
  } catch {
    groups.value = []
  } finally {
    loading.value = false
  }
}

watch(statusFilter, load)

onMounted(async () => {
  try {
    const { data } = await probesApi.list()
    probeMap.value = Object.fromEntries(data.map((p) => [p.id, p]))
  } catch {}
  await load()
})
</script>
