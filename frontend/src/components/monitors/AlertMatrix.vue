<template>
  <div class="space-y-4">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-sm font-semibold text-gray-200">{{ t('alert_matrix.title') }}</h2>
        <p class="text-xs text-gray-500 mt-1">{{ t('alert_matrix.subtitle_cards') }}</p>
      </div>
      <div class="flex items-center gap-2">
        <TemplatePicker
          :check-type="checkType"
          :has-existing-rows="activeRows.length > 0"
          @apply="applyTemplate"
        />
        <button
          @click="save"
          :disabled="saving || !dirty"
          class="btn-primary text-xs disabled:opacity-40"
        >
          {{ saving ? t('common.loading') : t('alert_matrix.save') }}
        </button>
      </div>
    </div>

    <div v-if="!channels.length" class="card text-sm text-gray-400">
      {{ t('alert_matrix.no_channels') }}
      <router-link to="/settings/alerts" class="text-blue-400 underline ml-1">
        {{ t('alert_matrix.create_channel') }}
      </router-link>
    </div>

    <template v-else>
      <div v-if="!activeRows.length" class="card text-sm text-gray-500 text-center py-8">
        {{ t('alert_matrix.empty_hint') }}
      </div>

      <div class="space-y-2">
        <ConditionCard
          v-for="row in activeRows"
          :key="row.condition"
          :row="row"
          :channels="channels"
          :impact-count="impactByCondition[row.condition] ?? null"
          @remove="removeRow(row.condition)"
        />
      </div>

      <div class="pt-1">
        <AddRuleMenu
          :available="availableConditions"
          :used="activeRows.map(r => r.condition)"
          @add="addRow"
        />
      </div>
    </template>

    <p v-if="error" class="text-xs text-red-400">{{ error }}</p>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api/client'
import ConditionCard from './alert-matrix/ConditionCard.vue'
import AddRuleMenu from './alert-matrix/AddRuleMenu.vue'
import TemplatePicker from './alert-matrix/TemplatePicker.vue'
import { conditionsForCheckType } from '../../constants/alertMatrix'

const props = defineProps({
  monitorId: { type: String, required: true },
  checkType: { type: String, default: 'http' },
})

const { t } = useI18n()

const channels = ref([])
const activeRows = ref([])
const initialSnapshot = ref('')
const saving = ref(false)
const error = ref('')
const impactByCondition = ref({})
let previewTimer = null

const availableConditions = computed(() => conditionsForCheckType(props.checkType))

const dirty = computed(() => JSON.stringify(activeRows.value) !== initialSnapshot.value)

function blankRow(condition) {
  return {
    condition,
    channel_ids: [],
    enabled: true,
    min_duration_seconds: 0,
    renotify_after_minutes: null,
    threshold_value: null,
    digest_minutes: 0,
    storm_window_seconds: null,
    storm_max_alerts: null,
    baseline_factor: null,
    anomaly_zscore_threshold: null,
    schedule: null,
  }
}

function addRow(condition) {
  activeRows.value.push(blankRow(condition))
}

function removeRow(condition) {
  activeRows.value = activeRows.value.filter(r => r.condition !== condition)
}

function applyTemplate(rows) {
  activeRows.value = rows.map(r => ({ ...blankRow(r.condition), ...r }))
}

async function load() {
  const [{ data: chList }, { data: matrix }] = await Promise.all([
    api.get('/alerts/channels'),
    api.get(`/alerts/monitors/${props.monitorId}/matrix`),
  ])
  channels.value = chList
  activeRows.value = matrix.rows.map(r => ({
    condition: r.condition,
    channel_ids: r.channels.map(c => c.id),
    enabled: r.enabled,
    min_duration_seconds: r.min_duration_seconds ?? 0,
    renotify_after_minutes: r.renotify_after_minutes,
    threshold_value: r.threshold_value,
    digest_minutes: r.digest_minutes ?? 0,
    storm_window_seconds: r.storm_window_seconds,
    storm_max_alerts: r.storm_max_alerts,
    baseline_factor: r.baseline_factor,
    anomaly_zscore_threshold: r.anomaly_zscore_threshold,
    schedule: r.schedule,
  }))
  initialSnapshot.value = JSON.stringify(activeRows.value)
}

async function save() {
  error.value = ''
  saving.value = true
  try {
    const payload = {
      rows: activeRows.value
        .filter(r => r.channel_ids.length > 0)
        .map(r => ({ ...r })),
    }
    await api.put(`/alerts/monitors/${props.monitorId}/matrix`, payload)
    await load()
  } catch (e) {
    error.value = e?.response?.data?.detail ?? String(e)
  } finally {
    saving.value = false
  }
}

async function refreshPreview() {
  if (!activeRows.value.length) {
    impactByCondition.value = {}
    return
  }
  try {
    const payload = { rows: activeRows.value.map(r => ({ ...r })) }
    const { data } = await api.post(`/alerts/monitors/${props.monitorId}/matrix/preview`, payload)
    const map = {}
    for (const c of data.counts) map[c.condition] = c.count
    impactByCondition.value = map
  } catch {
    // preview is best-effort — silent failure
  }
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer)
  previewTimer = setTimeout(refreshPreview, 500)
}

watch(activeRows, schedulePreview, { deep: true })

onMounted(load)
watch(() => props.monitorId, load)
onUnmounted(() => {
  if (previewTimer) clearTimeout(previewTimer)
})
</script>
