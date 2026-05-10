<template>
  <!-- Legacy SLO / Error Budget (visible if slo_target is set OR if editing) -->
  <div
    v-if="hasSlo && (monitor.slo_target != null || state.sloEditing.value)"
    class="card mb-6"
  >
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.slo_title') }}</h2>
      <div class="flex items-center gap-3">
        <span
          v-if="monitor.slo_target != null"
          class="text-xs font-mono"
          :class="{
            'text-emerald-400': state.sloData.value?.status === 'healthy',
            'text-amber-400': state.sloData.value?.status === 'at_risk',
            'text-red-400':
              state.sloData.value?.status === 'critical' ||
              state.sloData.value?.status === 'exhausted',
            'text-gray-400': !state.sloData.value,
          }"
        >
          {{ state.sloData.value ? state.sloData.value.status.toUpperCase() : '…' }}
        </span>
        <button
          class="btn-ghost text-xs"
          @click="state.sloEditing.value = !state.sloEditing.value"
        >
          ⚙ {{ t('monitor_detail.slo_configure') }}
        </button>
      </div>
    </div>
    <div v-if="monitor.slo_target != null && state.sloData.value" class="space-y-4">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_objective') }}</p>
          <p class="text-xl font-bold text-blue-400">{{ monitor.slo_target }}%</p>
          <p class="text-xs text-gray-600">{{ monitor.slo_window_days }}d</p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_actual_uptime') }}</p>
          <p
            class="text-xl font-bold"
            :class="state.sloData.value.uptime_pct >= monitor.slo_target ? 'text-emerald-400' : 'text-red-400'"
          >
            {{ state.sloData.value.uptime_pct?.toFixed(3) }}%
          </p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_budget_remaining') }}</p>
          <p
            class="text-xl font-bold"
            :class="state.sloData.value.error_budget_remaining_minutes >= 0 ? 'text-emerald-400' : 'text-red-400'"
          >
            {{ state.sloData.value.error_budget_remaining_minutes >= 0 ? '+' : '' }}{{ state.sloData.value.error_budget_remaining_minutes.toFixed(1) }}min
          </p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_burn_rate') }}</p>
          <p
            class="text-xl font-bold"
            :class="{
              'text-emerald-400': state.sloData.value.burn_rate <= 0.5,
              'text-amber-400': state.sloData.value.burn_rate > 0.5 && state.sloData.value.burn_rate <= 0.8,
              'text-red-400': state.sloData.value.burn_rate > 0.8,
            }"
          >{{ (state.sloData.value.burn_rate * 100).toFixed(1) }}%</p>
        </div>
      </div>
      <div>
        <div class="flex items-center justify-between mb-1.5 text-xs text-gray-500">
          <span>{{ t('monitor_detail.slo_budget_used') }}</span>
          <span>
            {{ state.sloData.value.error_budget_used_minutes.toFixed(1) }}min /
            {{ state.sloData.value.error_budget_total_minutes.toFixed(1) }}min
          </span>
        </div>
        <div class="w-full h-2.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all"
            :class="{
              'bg-emerald-500': state.sloData.value.burn_rate <= 0.5,
              'bg-amber-500': state.sloData.value.burn_rate > 0.5 && state.sloData.value.burn_rate <= 0.8,
              'bg-red-500': state.sloData.value.burn_rate > 0.8,
            }"
            :style="`width: ${Math.min(state.sloData.value.burn_rate * 100, 100)}%`"
          ></div>
        </div>
      </div>
    </div>
    <p
      v-else-if="monitor.slo_target != null && !state.sloData.value"
      class="text-gray-500 text-sm text-center py-4"
    >{{ t('common.loading') }}</p>

    <div
      v-if="state.sloEditing.value"
      class="mt-4 p-3 bg-gray-800/60 rounded-lg border border-gray-700 flex flex-wrap items-end gap-3"
    >
      <div>
        <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.slo_target') }}</label>
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
        <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.slo_window') }}</label>
        <input
          v-model.number="state.sloEditDays.value"
          type="number"
          min="1"
          max="365"
          class="input w-24 text-sm"
          placeholder="30"
        />
      </div>
      <button class="btn-primary text-xs h-9 px-4" @click="state.saveSlo">
        {{ t('monitor_detail.slo_save') }}
      </button>
      <button class="btn-ghost text-xs h-9 px-3" @click="state.sloEditing.value = false">
        {{ t('common.cancel') }}
      </button>
    </div>
  </div>

  <!-- V2 Global Health Engine -->
  <div v-if="monitor" class="card mb-6">
    <div class="flex items-center justify-between mb-4 gap-3 flex-wrap">
      <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.health_engine_title') }}</h2>
      <label class="flex items-center gap-2 cursor-pointer text-xs">
        <span :class="monitor.health_engine_enabled ? 'text-emerald-400' : 'text-gray-500'">
          {{ monitor.health_engine_enabled ? t('monitor_detail.health_engine_on') : t('monitor_detail.health_engine_off') }}
        </span>
        <input
          type="checkbox"
          :checked="monitor.health_engine_enabled"
          class="w-9 h-5 appearance-none bg-gray-700 rounded-full relative cursor-pointer transition-colors checked:bg-emerald-600 before:content-[''] before:absolute before:top-0.5 before:left-0.5 before:w-4 before:h-4 before:bg-white before:rounded-full before:transition-transform checked:before:translate-x-4"
          @change="state.toggleHealthEngine($event.target.checked)"
        />
      </label>
    </div>

    <p
      v-if="!monitor.health_engine_enabled && !state.sloRules.value.length"
      class="text-xs text-gray-500 mb-4"
    >
      {{ t('monitor_detail.health_engine_disabled_hint') }}
    </p>
    <div
      v-if="state.divergentProbes.value.length"
      class="mb-4 px-3 py-2 rounded-lg bg-amber-900/30 border border-amber-700/40 text-amber-200 text-xs flex items-start gap-2"
    >
      <span class="font-semibold flex-shrink-0">{{ t('monitor_detail.health_engine_divergent_label') }}:</span>
      <span class="flex flex-wrap gap-x-3 gap-y-1">
        <span v-for="d in state.divergentProbes.value" :key="d.probe_id" class="font-mono">
          {{ probeName(d.probe_id) }}
          <span class="text-amber-400/70">({{ Math.round(d.score * 100) }}%)</span>
        </span>
      </span>
    </div>

    <div
      v-if="state.healthState.value && state.healthState.value.exists"
      class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"
    >
      <div class="bg-gray-800/40 rounded-lg p-3 text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.health_engine_quorum') }}</p>
        <p
          class="text-xl font-bold"
          :class="state.healthState.value.quorum_down_ratio > 0 ? 'text-red-400' : 'text-emerald-400'"
        >
          {{ Math.round((state.healthState.value.quorum_down_ratio || 0) * 100) }}%
        </p>
        <p class="text-xs text-gray-600">
          {{ state.healthState.value.current_scope || t('monitor_detail.health_engine_all_up') }}
        </p>
      </div>
      <div class="bg-gray-800/40 rounded-lg p-3 text-center">
        <p class="text-xs text-gray-500">p50 / 5m</p>
        <p class="text-xl font-bold text-blue-400">
          {{ state.healthState.value.p50_5m != null ? state.healthState.value.p50_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
      <div class="bg-gray-800/40 rounded-lg p-3 text-center">
        <p class="text-xs text-gray-500">p95 / 5m</p>
        <p class="text-xl font-bold text-amber-400">
          {{ state.healthState.value.p95_5m != null ? state.healthState.value.p95_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
      <div class="bg-gray-800/40 rounded-lg p-3 text-center">
        <p class="text-xs text-gray-500">p99 / 5m</p>
        <p class="text-xl font-bold text-red-400">
          {{ state.healthState.value.p99_5m != null ? state.healthState.value.p99_5m.toFixed(0) + ' ms' : '—' }}
        </p>
      </div>
    </div>

    <div>
      <div class="flex items-center justify-between mb-2">
        <h3 class="text-xs font-semibold text-gray-400 uppercase">
          {{ t('monitor_detail.health_engine_rules') }}
        </h3>
        <button class="btn-ghost text-xs flex items-center gap-1" @click="state.openSloEditor()">
          <span>+</span> {{ t('monitor_detail.health_engine_add_rule') }}
        </button>
      </div>
      <p v-if="!state.sloRules.value.length" class="text-gray-500 text-sm py-2">
        {{ t('monitor_detail.health_engine_no_rules') }}
      </p>
      <ul v-else class="divide-y divide-gray-700/60">
        <li
          v-for="rule in state.sloRules.value"
          :key="rule.id"
          class="py-2 flex items-center gap-3 text-sm"
        >
          <span
            class="font-mono text-xs px-2 py-0.5 rounded border"
            :class="rule.enabled
              ? 'border-emerald-500/30 text-emerald-300 bg-emerald-500/10'
              : 'border-gray-600 text-gray-500'"
          >{{ rule.rule_type }}</span>
          <span class="text-gray-300 flex-1 min-w-0">{{ state.formatRuleSummary(rule) }}</span>
          <span v-if="rule.cooldown_seconds" class="text-xs text-gray-500">
            cooldown {{ rule.cooldown_seconds }}s
          </span>
          <button
            class="text-xs text-gray-500 hover:text-gray-300"
            @click="state.toggleSloRule(rule)"
          >
            {{ rule.enabled ? t('monitor_detail.health_engine_pause') : t('monitor_detail.health_engine_resume') }}
          </button>
          <button
            class="text-xs text-gray-500 hover:text-indigo-300"
            @click="state.openSloEditor(rule)"
          >{{ t('common.edit') }}</button>
          <button
            class="text-xs text-red-500 hover:text-red-400"
            @click="state.confirmDeleteSloRule(rule)"
          >✕</button>
        </li>
      </ul>
    </div>

    <!-- Editor modal -->
    <div
      v-if="state.sloEditor.value.open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      @click.self="state.sloEditor.value.open = false"
    >
      <div class="card w-full max-w-md">
        <h3 class="text-sm font-semibold text-gray-300 mb-3">
          {{ state.sloEditor.value.rule
            ? t('monitor_detail.health_engine_edit_rule')
            : t('monitor_detail.health_engine_new_rule') }}
        </h3>
        <div class="space-y-3 text-sm">
          <label class="block">
            <span class="text-xs text-gray-500 mb-1 block">
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
            <span class="text-xs text-gray-500 mb-1 block">
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
            <span class="text-xs text-gray-500 mb-1 block">
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
              <span class="text-xs text-gray-500 mb-1 block">
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
              <span class="text-xs text-gray-500 mb-1 block">
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
            <span class="text-xs text-gray-500 mb-1 block">
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
          <label class="flex items-center gap-2 text-xs text-gray-400">
            <input v-model="state.sloEditor.value.form.enabled" type="checkbox" />
            {{ t('monitor_detail.health_engine_rule_enabled') }}
          </label>
          <p v-if="state.sloEditor.value.error" class="text-xs text-red-400">
            {{ state.sloEditor.value.error }}
          </p>
        </div>
        <div class="flex justify-end gap-2 mt-4">
          <button
            class="btn-ghost text-xs"
            @click="state.sloEditor.value.open = false"
          >{{ t('common.cancel') }}</button>
          <button
            :disabled="state.sloEditor.value.saving"
            class="btn-primary text-xs"
            @click="state.saveSloRule"
          >
            {{ state.sloEditor.value.saving ? '…' : t('common.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  monitor: { type: Object, required: true },
  // Object returned by useMonitorSlo() — refs accessed via .value
  state: { type: Object, required: true },
  // True when the legacy SLO panel applies to this check_type (computed in parent)
  hasSlo: { type: Boolean, default: false },
  // Resolves a probe UUID to a display name (parent computes from probeMap)
  probeName: { type: Function, required: true },
})

const { t } = useI18n()
</script>
