<template>
  <div
    class="rounded-xl border bg-gray-900/40 transition-colors"
    :class="row.enabled ? 'border-gray-800' : 'border-gray-900 opacity-60'"
  >
    <div class="p-4 flex items-start gap-3">
      <label class="mt-1 cursor-pointer" :title="t('alert_matrix.enabled')">
        <input type="checkbox" v-model="row.enabled" class="w-4 h-4 accent-blue-500" />
      </label>

      <div class="flex-1 min-w-0">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="font-mono text-xs text-gray-200 truncate">{{ row.condition }}</div>
            <p class="text-[11px] text-gray-500 mt-0.5">
              {{ t('alert_matrix.conditions.' + row.condition) }}
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span
              v-if="impactCount !== null"
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border"
              :class="impactCount === 0
                ? 'border-gray-800 text-gray-500'
                : impactCount > 50
                  ? 'border-red-800/60 bg-red-900/20 text-red-300'
                  : impactCount > 10
                    ? 'border-amber-800/60 bg-amber-900/20 text-amber-300'
                    : 'border-emerald-800/60 bg-emerald-900/20 text-emerald-300'"
              :title="t('alert_matrix.impact.tooltip', { n: impactCount })"
            >
              ≈ {{ impactCount }} / 30j
            </span>
            <button
              type="button"
              @click="$emit('remove')"
              class="text-gray-600 hover:text-red-400 text-sm px-1"
              :title="t('alert_matrix.remove_rule')"
            >✕</button>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap gap-1.5">
          <ChannelChip
            v-for="ch in channels"
            :key="ch.id"
            :channel="ch"
            :active="row.channel_ids.includes(ch.id)"
            @toggle="toggleChannel(ch.id)"
          />
          <span v-if="!channels.length" class="text-[11px] text-gray-600 italic">
            {{ t('alert_matrix.no_channels_short') }}
          </span>
        </div>

        <details class="mt-3 group">
          <summary class="cursor-pointer text-[11px] text-gray-500 hover:text-gray-300 select-none">
            {{ t('alert_matrix.advanced') }}
            <span v-if="hasAdvancedValues" class="ml-1 text-blue-400">•</span>
          </summary>
          <div class="mt-3 pl-2 border-l-2 border-gray-800 space-y-3">
            <div class="flex flex-wrap items-center gap-3 text-xs text-gray-400">
              <label v-if="needsThreshold" class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.threshold') }}</span>
                <input v-model.number="row.threshold_value" type="number" min="0" class="input w-24 py-1" />
              </label>
              <label v-if="isAnomaly" class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.zscore_threshold') }}</span>
                <input v-model.number="row.anomaly_zscore_threshold" type="number" min="1" step="0.1" placeholder="3.0" class="input w-20 py-1" />
              </label>
              <label class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.min_duration') }}</span>
                <input v-model.number="row.min_duration_seconds" type="number" min="0" class="input w-20 py-1" />
                <span class="text-gray-600">s</span>
              </label>
              <label class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.renotify') }}</span>
                <input v-model.number="row.renotify_after_minutes" type="number" min="1" class="input w-20 py-1" />
                <span class="text-gray-600">min</span>
              </label>
              <label class="flex items-center gap-1.5">
                <span>{{ t('alerts.digest_minutes') }}</span>
                <input v-model.number="row.digest_minutes" type="number" min="0" max="1440" class="input w-20 py-1" />
                <span class="text-gray-600">min</span>
              </label>
            </div>
            <ScheduleEditor v-model="row.schedule" />
          </div>
        </details>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import ChannelChip from './ChannelChip.vue'
import ScheduleEditor from '../ScheduleEditor.vue'
import { needsThreshold as isThresholdCondition } from '../../../constants/alertMatrix'

const props = defineProps({
  row: { type: Object, required: true },
  channels: { type: Array, required: true },
  impactCount: { type: Number, default: null },
})
defineEmits(['remove'])
const { t } = useI18n()

const needsThreshold = computed(() => isThresholdCondition(props.row.condition))
const isAnomaly = computed(() => props.row.condition === 'anomaly_detection')

const hasAdvancedValues = computed(() => {
  const r = props.row
  return (
    (r.threshold_value != null) ||
    (r.min_duration_seconds > 0) ||
    (r.renotify_after_minutes != null) ||
    (r.digest_minutes > 0) ||
    !!r.schedule
  )
})

function toggleChannel(id) {
  const idx = props.row.channel_ids.indexOf(id)
  if (idx >= 0) props.row.channel_ids.splice(idx, 1)
  else props.row.channel_ids.push(id)
}
</script>
