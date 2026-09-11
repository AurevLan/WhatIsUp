<!--
  ConditionCard mutates `row.<field>` directly via v-model — the parent
  (AlertMatrix) passes a reactive list item, and Vue propagates the change
  back to the parent's state without any explicit update event. The
  vue/no-mutating-props warning is correct in principle but the alternative
  (7 computed wrappers + emit('update:row', ...) per field) would force the
  parent to thread a 2-way binding for every input here. Disabled for this
  file only.
-->
<!-- eslint-disable vue/no-mutating-props -->

<template>
  <div
    class="rounded-xl border bg-(--bg-surface) transition-colors"
    :class="row.enabled ? 'border-(--border)' : 'border-(--border) opacity-60'"
  >
    <div class="p-4 flex items-start gap-3">
      <label class="mt-1 cursor-pointer" :title="t('alert_matrix.enabled')">
        <input type="checkbox" v-model="row.enabled" class="w-4 h-4 accent-(--accent)" />
      </label>

      <div class="flex-1 min-w-0">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="font-mono text-xs text-(--text-1) truncate">{{ row.condition }}</div>
            <p class="text-[11px] text-(--text-3) mt-0.5">
              {{ t('alert_matrix.conditions.' + row.condition) }}
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span
              v-if="impactCount !== null"
              class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] border"
              :class="impactCount === 0
                ? 'border-(--border) text-(--text-3)'
                : impactCount > 50
                  ? 'border-[color-mix(in_srgb,var(--down)_60%,transparent)] bg-[color-mix(in_srgb,var(--down)_20%,transparent)] text-(--down)'
                  : impactCount > 10
                    ? 'border-[color-mix(in_srgb,var(--warn)_60%,transparent)] bg-[color-mix(in_srgb,var(--warn)_20%,transparent)] text-(--warn)'
                    : 'border-[color-mix(in_srgb,var(--up)_60%,transparent)] bg-[color-mix(in_srgb,var(--up)_20%,transparent)] text-(--up)'"
              :title="t('alert_matrix.impact.tooltip', { n: impactCount })"
            >
              ≈ {{ impactCount }} / 30j
            </span>
            <button
              type="button"
              @click="$emit('remove')"
              class="text-(--text-3) hover:text-(--down) text-sm px-1"
              :title="t('alert_matrix.remove_rule')"
              :aria-label="t('alert_matrix.remove_rule')"
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
          <span v-if="!channels.length" class="text-[11px] text-(--text-3) italic">
            {{ t('alert_matrix.no_channels_short') }}
          </span>
        </div>

        <details class="mt-3 group">
          <summary class="cursor-pointer text-[11px] text-(--text-3) hover:text-(--text-1) select-none">
            {{ t('alert_matrix.advanced') }}
            <span v-if="hasAdvancedValues" class="ml-1 text-(--accent)">•</span>
          </summary>
          <div class="mt-3 pl-2 border-l-2 border-(--border) space-y-3">
            <!-- F1-conditions — availability's quorum: any probe down (old
                 any_down) vs every probe down at once (old all_down). -->
            <div v-if="isAvailability" class="flex items-center gap-1.5 text-xs text-(--text-2)">
              <span>{{ t('alert_matrix.quorum_label') }}</span>
              <select
                :value="row.quorum_ratio >= 1.0 ? 'all' : 'any'"
                @change="row.quorum_ratio = $event.target.value === 'all' ? 1.0 : null"
                class="input py-1"
              >
                <option value="any">{{ t('alert_matrix.quorum_any') }}</option>
                <option value="all">{{ t('alert_matrix.quorum_all') }}</option>
              </select>
            </div>

            <!-- F4 — latency_anomaly's sensitivity mode: exactly one of
                 threshold_value/baseline_factor/anomaly_zscore_threshold. -->
            <div v-if="isLatency" class="flex flex-wrap items-center gap-3 text-xs text-(--text-2)">
              <label class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.latency_mode_label') }}</span>
                <select :value="latencyMode" @change="setLatencyMode($event.target.value)" class="input py-1">
                  <option value="absolute">{{ t('alert_matrix.latency_mode_absolute') }}</option>
                  <option value="relative">{{ t('alert_matrix.latency_mode_relative') }}</option>
                  <option value="statistical">{{ t('alert_matrix.latency_mode_statistical') }}</option>
                </select>
              </label>
              <label v-if="latencyMode === 'absolute'" class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.threshold') }}</span>
                <input v-model.number="row.threshold_value" type="number" min="0" class="input w-24 py-1" />
              </label>
              <label v-if="latencyMode === 'relative'" class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.baseline_factor') }}</span>
                <input v-model.number="row.baseline_factor" type="number" min="1.1" step="0.1" placeholder="2.0" class="input w-20 py-1" />
              </label>
              <label v-if="latencyMode === 'statistical'" class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.zscore_threshold') }}</span>
                <input v-model.number="row.anomaly_zscore_threshold" type="number" min="1" step="0.1" placeholder="3.0" class="input w-20 py-1" />
              </label>
            </div>

            <div class="flex flex-wrap items-center gap-3 text-xs text-(--text-2)">
              <label class="flex items-center gap-1.5">
                <span>{{ t('alert_matrix.min_duration') }}</span>
                <input v-model.number="row.min_duration_seconds" type="number" min="0" class="input w-20 py-1" />
                <span class="text-(--text-3)">s</span>
              </label>
              <label class="flex items-center gap-1.5">
                <span>{{ t('alerts.digest_minutes') }}</span>
                <input v-model.number="row.digest_minutes" type="number" min="0" max="1440" class="input w-20 py-1" />
                <span class="text-(--text-3)">min</span>
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
import { latencyModeOf } from '../../../constants/alertMatrix'

const props = defineProps({
  row: { type: Object, required: true },
  channels: { type: Array, required: true },
  impactCount: { type: Number, default: null },
})
defineEmits(['remove'])
const { t } = useI18n()

const isAvailability = computed(() => props.row.condition === 'availability')
const isLatency = computed(() => props.row.condition === 'latency_anomaly')
const latencyMode = computed(() => latencyModeOf(props.row))

function setLatencyMode(mode) {
  // Exactly one of the three fields may be set (schemas.alert.
  // assert_latency_rule_is_fireable) — switching mode clears the others.
  // eslint-disable-next-line vue/no-mutating-props
  props.row.threshold_value = mode === 'absolute' ? (props.row.threshold_value ?? null) : null
  // eslint-disable-next-line vue/no-mutating-props
  props.row.baseline_factor = mode === 'relative' ? (props.row.baseline_factor ?? 2.0) : null
  // eslint-disable-next-line vue/no-mutating-props
  props.row.anomaly_zscore_threshold = mode === 'statistical' ? (props.row.anomaly_zscore_threshold ?? 3.0) : null
}

const hasAdvancedValues = computed(() => {
  const r = props.row
  return (
    (r.threshold_value != null) ||
    (r.baseline_factor != null) ||
    (r.anomaly_zscore_threshold != null) ||
    (r.quorum_ratio != null) ||
    (r.min_duration_seconds > 0) ||
    (r.digest_minutes > 0) ||
    !!r.schedule
  )
})

function toggleChannel(id) {
  const idx = props.row.channel_ids.indexOf(id)
  // eslint-disable-next-line vue/no-mutating-props
  if (idx >= 0) props.row.channel_ids.splice(idx, 1)
  // eslint-disable-next-line vue/no-mutating-props
  else props.row.channel_ids.push(id)
}
</script>
