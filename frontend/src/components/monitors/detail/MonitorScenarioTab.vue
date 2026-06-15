<template>
  <div>
    <!-- Stats cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.uptime_24h') }}</p>
        <p
          class="text-2xl font-bold mt-1"
          :class="uptime24?.uptime_percent >= 99 ? 'text-(--up)' : 'text-(--down)'"
        >
          {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
        <UptimeViewSplit :stats="uptime24" />
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.uptime_7d') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--accent)">
          {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
        <UptimeViewSplit :stats="uptime7d" />
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.avg_duration') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--text-2)">
          {{ uptime24?.avg_response_time_ms ? (uptime24.avg_response_time_ms / 1000).toFixed(1) + 's' : '—' }}
        </p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.p95_duration') }}</p>
        <p class="text-2xl font-bold mt-1 text-(--text-2)">
          {{ uptime24?.p95_response_time_ms ? (uptime24.p95_response_time_ms / 1000).toFixed(1) + 's' : '—' }}
        </p>
      </div>
    </div>

    <!-- Edit / Duplicate / Maintenance links -->
    <div class="flex items-center justify-end gap-2 mb-3">
      <button
        class="btn-secondary btn-sm flex items-center gap-1.5"
        :title="t('monitors.duplicate')"
        @click="$emit('duplicate')"
      >
        <Copy class="w-3.5 h-3.5" /> {{ t('monitors.duplicate') }}
      </button>
      <button
        class="btn-secondary btn-sm flex items-center gap-1.5"
        :title="t('maintenance.schedule_maintenance')"
        @click="$emit('schedule-maintenance')"
      >
        <CalendarClock class="w-3.5 h-3.5" /> {{ t('maintenance.schedule_maintenance') }}
      </button>
      <button
        class="btn-secondary btn-sm flex items-center gap-1.5"
        :title="t('monitor_detail.edit')"
        @click="$emit('edit-monitor')"
      >
        ⚙ {{ t('monitor_detail.edit') }}
      </button>
    </div>

    <!-- Scenario run history -->
    <div class="card">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.recent_checks') }}</h2>
        <button
          :disabled="testing"
          class="btn-primary btn-sm flex items-center gap-2 disabled:opacity-50"
          @click="$emit('trigger-check')"
        >
          <template v-if="testing">
            <span class="w-2 h-2 rounded-full bg-(--accent) animate-pulse shrink-0"></span>
            <span v-if="testingState === 'queued'">{{ t('monitor_detail.testing_queued') }}</span>
            <span v-else>
              {{ t('monitor_detail.testing_running') }}
              {{ testingElapsed > 0 ? t('monitor_detail.testing_elapsed', { s: testingElapsed }) : '' }}
            </span>
          </template>
          <template v-else>▶ {{ t('monitor_detail.test_now') }}</template>
        </button>
      </div>
      <div v-if="results.length" class="space-y-1">
        <div
          v-for="r in results.slice(0, 30)"
          :key="r.id"
          class="rounded-lg border transition-colors"
          :class="newResultId === r.id
            ? 'border-(--accent-border) bg-(--accent-glow) shadow-[0_0_0_2px_var(--accent-glow)]'
            : selectedRunId === r.id
              ? 'border-(--accent-border) bg-(--accent-glow)'
              : 'border-(--border) hover:border-(--border-hover) bg-(--bg-surface)'"
        >
          <button
            class="w-full flex items-center gap-3 px-4 py-3 text-left"
            @click="toggleRun(r.id)"
          >
            <span
              class="w-2 h-2 rounded-full shrink-0"
              :class="{
                'bg-(--up)': r.status === 'up',
                'bg-(--down)': r.status === 'down' || r.status === 'error',
                'bg-(--warn)': r.status === 'timeout',
              }"
            ></span>
            <span class="text-xs text-(--text-2) whitespace-nowrap w-36 shrink-0">
              {{ formatDate(r.checked_at) }}
            </span>
            <span
              class="text-xs font-medium shrink-0 w-24 truncate"
              :style="`color:${probeColor(r.probe_id)}`"
            >
              {{ probeName(r.probe_id) }}
            </span>
            <span
              class="text-xs font-medium px-2 py-0.5 rounded-full shrink-0"
              :class="{
                'bg-[color-mix(in_srgb,var(--up)_12%,transparent)] text-(--up)': r.status === 'up',
                'bg-[color-mix(in_srgb,var(--down)_12%,transparent)] text-(--down)': r.status === 'down' || r.status === 'error',
                'bg-[color-mix(in_srgb,var(--warn)_12%,transparent)] text-(--warn)': r.status === 'timeout',
              }"
            >{{ r.status }}</span>
            <span class="text-xs flex-1 text-left" v-if="r.scenario_result">
              <span :class="r.status === 'up' ? 'text-(--up)' : 'text-(--down)'">
                {{ r.scenario_result.steps_passed }}/{{ r.scenario_result.steps_total }} steps
              </span>
              <span v-if="r.scenario_result.steps_warned > 0" class="text-(--warn) ml-2">
                ⚠ {{ r.scenario_result.steps_warned }} warning(s)
              </span>
              <span v-if="r.scenario_result.failed_step_label" class="text-(--text-3) ml-2">
                · failed: {{ r.scenario_result.failed_step_label }}
              </span>
            </span>
            <span v-else class="flex-1"></span>
            <span class="text-xs text-(--text-3) font-mono shrink-0">
              {{ r.response_time_ms ? (r.response_time_ms / 1000).toFixed(2) + 's' : '—' }}
            </span>
            <span
              class="text-(--text-3) text-xs shrink-0 ml-1 transition-transform"
              :class="selectedRunId === r.id ? 'rotate-180' : ''"
            >▾</span>
          </button>

          <div
            v-if="selectedRunId === r.id && r.scenario_result?.steps?.length"
            class="px-4 pb-3 pt-1 border-t border-(--border) space-y-1"
          >
            <div class="flex gap-0.5 h-2 rounded overflow-hidden mb-3">
              <div
                v-for="s in r.scenario_result.steps"
                :key="s.index"
                class="rounded-sm"
                :class="s.status === 'passed' ? 'bg-(--up)' : s.status === 'warned' ? 'bg-(--warn)' : 'bg-(--down)'"
                :style="`flex: ${s.duration_ms || 1}`"
                :title="`${s.label || s.type}: ${s.duration_ms}ms`"
              ></div>
            </div>

            <template v-for="s in r.scenario_result.steps" :key="s.index">
              <div
                v-if="s.type === 'group'"
                class="col-span-full py-1 mt-2 mb-1 border-t border-(--border)"
              >
                <span class="text-xs font-semibold text-(--text-2) uppercase tracking-wider">
                  {{ s.label }}
                </span>
              </div>
              <div
                v-else
                class="flex items-center gap-3 py-1.5 px-3 rounded"
                :class="s.status === 'passed'
                  ? 'bg-[color-mix(in_srgb,var(--up)_10%,transparent)]'
                  : s.status === 'warned'
                    ? 'bg-[color-mix(in_srgb,var(--warn)_10%,transparent)]'
                    : 'bg-[color-mix(in_srgb,var(--down)_12%,transparent)]'"
              >
                <span
                  class="text-sm shrink-0"
                  :class="s.status === 'passed'
                    ? 'text-(--up)'
                    : s.status === 'warned'
                      ? 'text-(--warn)'
                      : 'text-(--down)'"
                >
                  {{ s.status === 'warned' ? '⚠' : (s.status === 'passed' ? '✓' : '✗') }}
                </span>
                <span class="text-xs text-(--text-3) shrink-0 w-5 text-right">{{ s.index + 1 }}</span>
                <span
                  class="text-xs px-1.5 py-0.5 rounded font-mono shrink-0"
                  :class="stepTypeBadgeClass(s.type)"
                >{{ s.type }}</span>
                <span class="text-sm text-(--text-2) flex-1 truncate">{{ s.label }}</span>
                <span
                  v-if="s.continue_on_fail"
                  class="text-xs px-1 py-0.5 rounded bg-[color-mix(in_srgb,var(--warn)_12%,transparent)] text-(--warn) shrink-0"
                >skip on fail</span>
                <span
                  v-if="s.error"
                  class="text-xs text-(--down) truncate max-w-xs"
                  :title="s.error"
                >{{ s.error }}</span>
                <span class="text-xs text-(--text-3) shrink-0 font-mono">
                  {{ s.duration_ms != null ? s.duration_ms + 'ms' : '' }}
                </span>
                <button
                  v-if="s.screenshot"
                  class="shrink-0 rounded overflow-hidden border border-(--border) hover:border-(--accent-border) transition-colors"
                  title="Voir le screenshot"
                  @click.stop="$emit('open-screenshot', { src: s.screenshot, label: s.label || s.type })"
                >
                  <img
                    :src="s.screenshot"
                    :alt="s.label || s.type || 'Scenario step screenshot'"
                    class="w-16 h-9 object-cover"
                  />
                </button>
              </div>
            </template>
          </div>

          <div
            v-else-if="selectedRunId === r.id && r.scenario_result && !r.scenario_result.steps?.length"
            class="px-4 pb-3 pt-1 border-t border-(--border) text-xs text-(--text-3)"
          >
            {{ t('monitor_detail.scenario_no_detail') }}
          </div>

          <div
            v-else-if="selectedRunId === r.id && !r.scenario_result && r.error_message"
            class="px-4 pb-3 pt-2 border-t border-(--border)"
          >
            <p class="text-xs font-semibold text-(--text-2) mb-1">{{ t('common.error') }}</p>
            <p class="text-xs text-(--down) font-mono break-all">{{ r.error_message }}</p>
          </div>

          <div
            v-if="selectedRunId === r.id && r.scenario_result?.web_vitals && Object.keys(r.scenario_result.web_vitals).length"
            class="px-4 pb-3 pt-2 border-t border-(--border)"
          >
            <p class="text-xs font-semibold text-(--text-2) mb-2">{{ t('monitor_detail.web_vitals') }}</p>
            <div class="flex flex-wrap gap-4">
              <div v-if="r.scenario_result.web_vitals.lcp_ms != null" class="flex items-center gap-1.5">
                <span class="text-xs text-(--text-3) font-mono">LCP</span>
                <span
                  class="text-xs font-mono font-semibold"
                  :class="r.scenario_result.web_vitals.lcp_ms <= 2500 ? 'text-(--up)'
                    : r.scenario_result.web_vitals.lcp_ms <= 4000 ? 'text-(--warn)'
                    : 'text-(--down)'"
                >
                  {{ (r.scenario_result.web_vitals.lcp_ms / 1000).toFixed(2) }}s
                </span>
                <span class="text-xs">
                  {{ r.scenario_result.web_vitals.lcp_ms <= 2500 ? '✅' : r.scenario_result.web_vitals.lcp_ms <= 4000 ? '⚠️' : '❌' }}
                </span>
              </div>
              <div v-if="r.scenario_result.web_vitals.cls != null" class="flex items-center gap-1.5">
                <span class="text-xs text-(--text-3) font-mono">CLS</span>
                <span
                  class="text-xs font-mono font-semibold"
                  :class="r.scenario_result.web_vitals.cls <= 0.1 ? 'text-(--up)'
                    : r.scenario_result.web_vitals.cls <= 0.25 ? 'text-(--warn)'
                    : 'text-(--down)'"
                >
                  {{ r.scenario_result.web_vitals.cls.toFixed(3) }}
                </span>
                <span class="text-xs">
                  {{ r.scenario_result.web_vitals.cls <= 0.1 ? '✅' : r.scenario_result.web_vitals.cls <= 0.25 ? '⚠️' : '❌' }}
                </span>
              </div>
              <div v-if="r.scenario_result.web_vitals.inp_ms != null" class="flex items-center gap-1.5">
                <span class="text-xs text-(--text-3) font-mono">INP</span>
                <span
                  class="text-xs font-mono font-semibold"
                  :class="r.scenario_result.web_vitals.inp_ms <= 200 ? 'text-(--up)'
                    : r.scenario_result.web_vitals.inp_ms <= 500 ? 'text-(--warn)'
                    : 'text-(--down)'"
                >
                  {{ r.scenario_result.web_vitals.inp_ms }}ms
                </span>
                <span class="text-xs">
                  {{ r.scenario_result.web_vitals.inp_ms <= 200 ? '✅' : r.scenario_result.web_vitals.inp_ms <= 500 ? '⚠️' : '❌' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <p v-else class="text-(--text-3) text-sm text-center py-6">{{ t('monitor_detail.no_data') }}</p>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { Copy, CalendarClock } from 'lucide-vue-next'
import UptimeViewSplit from '../UptimeViewSplit.vue'

const props = defineProps({
  uptime24: { type: Object, default: null },
  uptime7d: { type: Object, default: null },
  results: { type: Array, default: () => [] },
  selectedRunId: { type: String, default: null },
  newResultId: { type: String, default: null },
  testing: { type: Boolean, default: false },
  testingState: { type: String, default: null },
  testingElapsed: { type: Number, default: 0 },
  formatDate: { type: Function, required: true },
  probeColor: { type: Function, required: true },
  probeName: { type: Function, required: true },
  stepTypeBadgeClass: { type: Function, required: true },
})

const emit = defineEmits([
  'update:selectedRunId',
  'trigger-check',
  'duplicate',
  'schedule-maintenance',
  'edit-monitor',
  'open-screenshot',
])

const { t } = useI18n()

function toggleRun(id) {
  emit('update:selectedRunId', props.selectedRunId === id ? null : id)
}
</script>
