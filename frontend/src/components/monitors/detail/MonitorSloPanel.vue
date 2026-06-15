<template>
  <!-- Legacy SLO / Error Budget (visible if slo_target is set OR if editing) -->
  <div
    v-if="hasSlo && (monitor.slo_target != null || state.sloEditing.value)"
    class="card mb-6"
  >
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.slo_title') }}</h2>
      <div class="flex items-center gap-3">
        <span
          v-if="monitor.slo_target != null"
          class="text-xs font-mono"
          :class="{
            'text-(--up)': state.sloData.value?.status === 'healthy',
            'text-(--warn)': state.sloData.value?.status === 'at_risk',
            'text-(--down)':
              state.sloData.value?.status === 'critical' ||
              state.sloData.value?.status === 'exhausted',
            'text-(--text-2)': !state.sloData.value,
          }"
        >
          {{ state.sloData.value ? state.sloData.value.status.toUpperCase() : '…' }}
        </span>
        <button
          class="btn-ghost btn-sm"
          @click="state.sloEditing.value = !state.sloEditing.value"
        >
          ⚙ {{ t('monitor_detail.slo_configure') }}
        </button>
      </div>
    </div>
    <div v-if="monitor.slo_target != null && state.sloData.value" class="space-y-4">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
          <p class="text-xs text-(--text-3)">{{ t('monitor_detail.slo_objective') }}</p>
          <p class="text-xl font-bold font-display text-(--accent)">{{ monitor.slo_target }}%</p>
          <p class="text-xs text-(--text-3)">{{ monitor.slo_window_days }}d</p>
        </div>
        <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
          <p class="text-xs text-(--text-3)">{{ t('monitor_detail.slo_actual_uptime') }}</p>
          <p
            class="text-xl font-bold font-display"
            :class="state.sloData.value.uptime_pct >= monitor.slo_target ? 'text-(--up)' : 'text-(--down)'"
          >
            {{ state.sloData.value.uptime_pct?.toFixed(3) }}%
          </p>
        </div>
        <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
          <p class="text-xs text-(--text-3)">{{ t('monitor_detail.slo_budget_remaining') }}</p>
          <p
            class="text-xl font-bold font-display"
            :class="state.sloData.value.error_budget_remaining_minutes >= 0 ? 'text-(--up)' : 'text-(--down)'"
          >
            {{ state.sloData.value.error_budget_remaining_minutes >= 0 ? '+' : '' }}{{ state.sloData.value.error_budget_remaining_minutes.toFixed(1) }}min
          </p>
        </div>
        <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
          <p class="text-xs text-(--text-3)">{{ t('monitor_detail.slo_burn_rate') }}</p>
          <p
            class="text-xl font-bold font-display"
            :class="{
              'text-(--up)': state.sloData.value.burn_rate <= 0.5,
              'text-(--warn)': state.sloData.value.burn_rate > 0.5 && state.sloData.value.burn_rate <= 0.8,
              'text-(--down)': state.sloData.value.burn_rate > 0.8,
            }"
          >{{ (state.sloData.value.burn_rate * 100).toFixed(1) }}%</p>
        </div>
      </div>
      <div>
        <div class="flex items-center justify-between mb-1.5 text-xs text-(--text-3)">
          <span>{{ t('monitor_detail.slo_budget_used') }}</span>
          <span>
            {{ state.sloData.value.error_budget_used_minutes.toFixed(1) }}min /
            {{ state.sloData.value.error_budget_total_minutes.toFixed(1) }}min
          </span>
        </div>
        <div class="w-full h-2.5 bg-(--bg-surface-2) rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all"
            :class="{
              'bg-(--up)': state.sloData.value.burn_rate <= 0.5,
              'bg-(--warn)': state.sloData.value.burn_rate > 0.5 && state.sloData.value.burn_rate <= 0.8,
              'bg-(--down)': state.sloData.value.burn_rate > 0.8,
            }"
            :style="`width: ${Math.min(state.sloData.value.burn_rate * 100, 100)}%`"
          ></div>
        </div>
      </div>
    </div>
    <p
      v-else-if="monitor.slo_target != null && !state.sloData.value"
      class="text-(--text-3) text-sm text-center py-4"
    >{{ t('common.loading') }}</p>

    <div
      v-if="state.sloEditing.value"
      class="mt-4 p-3 bg-(--bg-surface-2) rounded-lg border border-(--border) flex flex-wrap items-end gap-3"
    >
      <div>
        <label class="text-xs text-(--text-3) block mb-1">{{ t('monitor_detail.slo_target') }}</label>
        <input
          v-model.number="state.sloEditTarget.value"
          type="number"
          min="0"
          max="100"
          step="0.1"
          class="input w-32 text-sm"
          placeholder="99.9"
        />
      </div>
      <div>
        <label class="text-xs text-(--text-3) block mb-1">{{ t('monitor_detail.slo_window') }}</label>
        <input
          v-model.number="state.sloEditDays.value"
          type="number"
          min="1"
          max="365"
          class="input w-24 text-sm"
          placeholder="30"
        />
      </div>
      <button class="btn-primary btn-sm" @click="state.saveSlo">
        {{ t('monitor_detail.slo_save') }}
      </button>
      <button class="btn-ghost btn-sm" @click="state.sloEditing.value = false">
        {{ t('common.cancel') }}
      </button>
    </div>
  </div>

  <!-- V2 Global Health Engine -->
  <div v-if="monitor" class="card mb-6">
    <div class="flex items-center justify-between mb-4 gap-3 flex-wrap">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.health_engine_title') }}</h2>
      <label class="flex items-center gap-2 cursor-pointer text-xs">
        <span :class="monitor.health_engine_enabled ? 'text-(--up)' : 'text-(--text-3)'">
          {{ monitor.health_engine_enabled ? t('monitor_detail.health_engine_on') : t('monitor_detail.health_engine_off') }}
        </span>
        <input
          type="checkbox"
          :checked="monitor.health_engine_enabled"
          class="w-9 h-5 appearance-none bg-(--bg-surface-2) rounded-full relative cursor-pointer transition-colors checked:bg-(--up) before:content-[''] before:absolute before:top-0.5 before:left-0.5 before:w-4 before:h-4 before:bg-white before:rounded-full before:transition-transform checked:before:translate-x-4"
          @change="state.toggleHealthEngine($event.target.checked)"
        />
      </label>
    </div>

    <p
      v-if="!monitor.health_engine_enabled && !state.sloRules.value.length"
      class="text-xs text-(--text-3) mb-4"
    >
      {{ t('monitor_detail.health_engine_disabled_hint') }}
    </p>
    <div
      v-if="state.divergentProbes.value.length"
      class="mb-4 px-3 py-2 rounded-lg bg-[color-mix(in_srgb,var(--warn)_12%,transparent)] border border-[color-mix(in_srgb,var(--warn)_25%,transparent)] text-(--warn) text-xs flex items-start gap-2"
    >
      <span class="font-semibold flex-shrink-0">{{ t('monitor_detail.health_engine_divergent_label') }}:</span>
      <span class="flex flex-wrap gap-x-3 gap-y-1">
        <span v-for="d in state.divergentProbes.value" :key="d.probe_id" class="font-mono">
          {{ probeName(d.probe_id) }}
          <span class="text-(--warn)">({{ Math.round(d.score * 100) }}%)</span>
        </span>
      </span>
    </div>

    <div
      v-if="state.healthState.value && state.healthState.value.exists"
      class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"
    >
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.health_engine_quorum') }}</p>
        <p
          class="text-xl font-bold font-display"
          :class="state.healthState.value.quorum_down_ratio > 0 ? 'text-(--down)' : 'text-(--up)'"
        >
          {{ Math.round((state.healthState.value.quorum_down_ratio || 0) * 100) }}%
        </p>
        <p class="text-xs text-(--text-3)">
          {{ state.healthState.value.current_scope || t('monitor_detail.health_engine_all_up') }}
        </p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">p50 / 5m</p>
        <p class="text-xl font-bold font-display text-(--accent)">
          {{ state.healthState.value.p50_5m != null ? state.healthState.value.p50_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">p95 / 5m</p>
        <p class="text-xl font-bold font-display text-(--warn)">
          {{ state.healthState.value.p95_5m != null ? state.healthState.value.p95_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">p99 / 5m</p>
        <p class="text-xl font-bold font-display text-(--down)">
          {{ state.healthState.value.p99_5m != null ? state.healthState.value.p99_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
    </div>

    <div>
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-semibold text-(--text-2) uppercase">
          {{ t('monitor_detail.health_engine_rules') }}
        </h3>
        <button class="btn-ghost btn-sm flex items-center gap-1" @click="state.openSloEditor()">
          <span>+</span> {{ t('monitor_detail.health_engine_add_rule') }}
        </button>
      </div>
      <p v-if="!state.sloRules.value.length" class="text-(--text-3) text-sm py-2">
        {{ t('monitor_detail.health_engine_no_rules') }}
      </p>
      <ul v-else class="divide-y divide-(--border)">
        <li
          v-for="rule in state.sloRules.value"
          :key="rule.id"
          class="py-2 flex items-center gap-3 text-sm"
        >
          <span
            class="font-mono text-xs px-2 py-0.5 rounded border"
            :class="rule.enabled
              ? 'border-[color-mix(in_srgb,var(--up)_30%,transparent)] text-(--up) bg-[color-mix(in_srgb,var(--up)_10%,transparent)]'
              : 'border-(--border) text-(--text-3)'"
          >{{ rule.rule_type }}</span>
          <span class="text-(--text-2) flex-1 min-w-0">{{ state.formatRuleSummary(rule) }}</span>
          <span v-if="rule.cooldown_seconds" class="text-xs text-(--text-3)">
            cooldown {{ rule.cooldown_seconds }}s
          </span>
          <button
            class="text-xs text-(--text-3) hover:text-(--text-1)"
            @click="state.toggleSloRule(rule)"
          >
            {{ rule.enabled ? t('monitor_detail.health_engine_pause') : t('monitor_detail.health_engine_resume') }}
          </button>
          <button
            class="text-xs text-(--text-3) hover:text-(--accent)"
            @click="state.openSloEditor(rule)"
          >{{ t('common.edit') }}</button>
          <button
            class="text-xs text-(--down)"
            :aria-label="t('common.delete')"
            @click="state.confirmDeleteSloRule(rule)"
          >✕</button>
        </li>
      </ul>
    </div>

    <!-- Editor modal -->
    <BaseModal :model-value="state.sloEditor.value.open"
      :title="state.sloEditor.value.rule
        ? t('monitor_detail.health_engine_edit_rule')
        : t('monitor_detail.health_engine_new_rule')"
      @update:model-value="state.sloEditor.value.open = $event">
        <div class="space-y-3 text-sm">
          <label class="block">
            <span class="text-xs text-(--text-3) mb-1 block">
              {{ t('monitor_detail.health_engine_rule_type') }}
            </span>
            <select
              v-model="state.sloEditor.value.form.rule_type"
              :disabled="!!state.sloEditor.value.rule"
              class="input w-full text-xs"
            >
              <option value="quorum_down">quorum_down</option>
              <option value="quorum_slow">quorum_slow</option>
            </select>
          </label>
          <label v-if="state.sloEditor.value.form.rule_type === 'quorum_down'" class="block">
            <span class="text-xs text-(--text-3) mb-1 block">
              {{ t('monitor_detail.health_engine_quorum_ratio') }} (0–1)
            </span>
            <input
              v-model.number="state.sloEditor.value.form.quorum_ratio"
              type="number"
              min="0"
              max="1"
              step="0.05"
              class="input w-full text-xs"
            />
          </label>
          <label v-if="state.sloEditor.value.form.rule_type === 'quorum_slow'" class="block">
            <span class="text-xs text-(--text-3) mb-1 block">
              {{ t('monitor_detail.health_engine_p95_threshold') }} (ms)
            </span>
            <input
              v-model.number="state.sloEditor.value.form.p95_threshold_ms"
              type="number"
              min="1"
              class="input w-full text-xs"
            />
          </label>
          <div class="grid grid-cols-2 gap-3">
            <label class="block">
              <span class="text-xs text-(--text-3) mb-1 block">
                {{ t('monitor_detail.health_engine_window') }} (s)
              </span>
              <input
                v-model.number="state.sloEditor.value.form.window_seconds"
                type="number"
                min="30"
                max="86400"
                class="input w-full text-xs"
              />
            </label>
            <label class="block">
              <span class="text-xs text-(--text-3) mb-1 block">
                {{ t('monitor_detail.health_engine_min_probes') }}
              </span>
              <input
                v-model.number="state.sloEditor.value.form.min_probes"
                type="number"
                min="1"
                class="input w-full text-xs"
              />
            </label>
          </div>
          <label class="block">
            <span class="text-xs text-(--text-3) mb-1 block">
              {{ t('monitor_detail.health_engine_cooldown') }} (s)
            </span>
            <input
              v-model.number="state.sloEditor.value.form.cooldown_seconds"
              type="number"
              min="0"
              max="86400"
              class="input w-full text-xs"
            />
          </label>
          <label class="flex items-center gap-2 text-xs text-(--text-2)">
            <input v-model="state.sloEditor.value.form.enabled" type="checkbox" />
            {{ t('monitor_detail.health_engine_rule_enabled') }}
          </label>
          <p v-if="state.sloEditor.value.error" class="text-xs text-(--down)">
            {{ state.sloEditor.value.error }}
          </p>
        </div>
        <template #footer>
          <button
            class="btn-ghost btn-sm ml-auto"
            @click="state.sloEditor.value.open = false"
          >{{ t('common.cancel') }}</button>
          <button
            :disabled="state.sloEditor.value.saving"
            class="btn-primary btn-sm"
            @click="state.saveSloRule"
          >
            {{ state.sloEditor.value.saving ? '…' : t('common.save') }}
          </button>
        </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { SloStateKey } from './injectionKeys'

defineProps({
  monitor: { type: Object, required: true },
  // True when the legacy SLO panel applies to this check_type (computed in parent)
  hasSlo: { type: Boolean, default: false },
  // Resolves a probe UUID to a display name (parent computes from probeMap)
  probeName: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(SloStateKey, sloState).
// Mutations via `state.x.value = …` are intentional and don't trip
// vue/no-mutating-props through inject.
const state = inject(SloStateKey)

const { t } = useI18n()
</script>
