<template>
  <div class="px-3 py-3 bg-(--bg-surface-2)">
    <p v-if="loading" class="text-xs text-(--text-3)">{{ t('common.loading') }}</p>

    <p v-else-if="error" class="text-xs text-(--down)">{{ error }}</p>

    <p v-else-if="!rows.length" class="text-xs text-(--text-3)">
      {{ t('correlation.no_metrics') }}
    </p>

    <template v-else>
      <p class="text-xs text-(--text-3) mb-2">
        {{ t('correlation.window_help', { minutes: windowMinutes }) }}
      </p>
      <div class="overflow-x-auto">
        <table class="w-full text-xs min-w-[34rem]">
          <thead>
            <tr class="text-(--text-3) text-left">
              <th class="py-1 pr-3 font-medium">{{ t('correlation.col_metric') }}</th>
              <th class="py-1 pr-3 font-medium">{{ t('correlation.col_during') }}</th>
              <th class="py-1 pr-3 font-medium">{{ t('correlation.col_baseline') }}</th>
              <th class="py-1 font-medium">{{ t('correlation.col_change') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.key" class="border-t border-(--border)">
              <td class="py-1 pr-3 font-mono text-(--text-2)">{{ row.key }}</td>
              <td class="py-1 pr-3 text-(--text-2)">{{ row.during }}</td>
              <td class="py-1 pr-3 text-(--text-3)">{{ row.baseline }}</td>
              <td class="py-1" :class="row.changeClass">{{ row.change }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- Said plainly, and said every time: a ranked list invites the reader to
           infer a cause, and this panel cannot support that inference. -->
      <p class="text-xs text-(--text-3) mt-2">{{ t('correlation.disclaimer') }}</p>
    </template>
  </div>
</template>

<script setup>
// Plan V2, C-3 — what the tenant's own metrics did around this incident.
// The blackbox checks say *that* it broke; this says what else moved at the
// same moment. Correlation only: nothing here claims a cause, and the wording
// is deliberate rather than cautious boilerplate.
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { incidentUpdatesApi } from '../../api/incidentUpdates'

const props = defineProps({ incidentId: { type: String, required: true } })
const { t } = useI18n()

const loading = ref(false)
const error = ref('')
const data = ref(null)

function formatLabels(labels) {
  const entries = Object.entries(labels || {}).sort(([a], [b]) => a.localeCompare(b))
  return entries.length ? `{${entries.map(([k, v]) => `${k}="${v}"`).join(',')}}` : ''
}

function formatValue(value, unit) {
  if (value === null || value === undefined) return '—'
  const rounded = Math.round(value * 1000) / 1000
  return unit ? `${rounded} ${unit}` : String(rounded)
}

const windowMinutes = computed(() =>
  data.value ? Math.round(data.value.window_seconds / 60) : 0,
)

const rows = computed(() =>
  (data.value?.series ?? []).map((s) => {
    let change
    let changeClass = 'text-(--text-3)'
    if (s.change_ratio !== null && s.change_ratio !== undefined) {
      const pct = Math.round(s.change_ratio * 100)
      change = `${pct >= 0 ? '+' : ''}${pct}%`
      // Colour by direction, not by judgement: a metric going up is not
      // inherently bad (a queue draining is a drop, a cache warming is a rise).
      changeClass = pct === 0 ? 'text-(--text-3)' : 'text-(--text-1)'
    } else if (s.not_comparable === 'zero_baseline' && s.change_absolute !== null) {
      const delta = Math.round(s.change_absolute * 1000) / 1000
      change = `${delta >= 0 ? '+' : ''}${delta}${s.unit ? ` ${s.unit}` : ''}`
      changeClass = 'text-(--text-1)'
    } else {
      change = t(`correlation.reason_${s.not_comparable ?? 'unknown'}`)
    }
    return {
      key: `${s.metric_name}${formatLabels(s.labels)}`,
      during: formatValue(s.incident_avg, s.unit),
      baseline: formatValue(s.baseline_avg, s.unit),
      change,
      changeClass,
    }
  }),
)

async function load() {
  if (!props.incidentId) return
  loading.value = true
  error.value = ''
  try {
    const { data: payload } = await incidentUpdatesApi.metricCorrelation(props.incidentId, {
      skipErrorToast: true,
    })
    data.value = payload
  } catch (e) {
    error.value = e.response?.data?.detail || t('common.error')
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.incidentId, load)
</script>
