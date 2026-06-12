<template>
  <!-- DNS: value changelog -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.dns_change_history') }}</h2>
      <span class="text-xs text-gray-500 font-mono bg-gray-800 px-2 py-1 rounded">
        {{ monitor.dns_record_type || 'A' }} · {{ formatTarget(monitor) }}
      </span>
    </div>
    <div v-if="state.changelog.value.length" class="space-y-2">
      <div v-for="(entry, i) in state.changelog.value" :key="i"
        class="flex items-start gap-3 py-2 px-3 rounded-lg"
        :class="entry.old_value === null ? 'bg-blue-950/30' : 'bg-amber-950/30'"
      >
        <!-- Icon -->
        <span class="text-base mt-0.5 shrink-0">{{ entry.old_value === null ? '🔵' : '🔄' }}</span>

        <!-- Date + probe -->
        <div class="shrink-0 w-36">
          <p class="text-xs text-gray-400">{{ formatDate(entry.checked_at) }}</p>
          <p class="text-xs font-medium mt-0.5" :style="`color:${probeColor(entry.probe_id)}`">
            {{ probeName(entry.probe_id) }}
          </p>
        </div>

        <!-- Change arrow -->
        <div class="flex-1 font-mono text-sm">
          <div v-if="entry.old_value !== null" class="flex items-center gap-2 flex-wrap">
            <span class="text-red-400 line-through text-xs">{{ entry.old_value || '(empty)' }}</span>
            <span class="text-gray-600">→</span>
            <span :class="entry.new_value ? 'text-emerald-400' : 'text-gray-500'">
              {{ entry.new_value || '(resolution failed)' }}
            </span>
          </div>
          <div v-else>
            <span class="text-blue-400">First value: {{ entry.new_value || '—' }}</span>
          </div>
        </div>
      </div>
    </div>
    <p v-else class="text-gray-500 text-sm text-center py-4">No changes detected in the loaded period</p>
  </div>

  <!-- DNS drift card (always visible for DNS monitors) -->
  <div class="card mb-6">
    <h2 class="text-sm font-semibold text-gray-300 mb-4">{{ t('monitors.dns_drift.label') }}</h2>

    <!-- Toggles -->
    <div class="space-y-3 mb-4">
      <label class="flex items-center justify-between cursor-pointer gap-4">
        <div>
          <p class="text-sm text-gray-300">{{ t('monitors.dns_drift.label') }}</p>
          <p class="text-xs text-gray-500">{{ t('monitors.dns_drift.desc') }}</p>
        </div>
        <button type="button" @click="state.toggleSetting('dns_drift_alert')"
          :class="monitor.dns_drift_alert ? 'bg-emerald-600' : 'bg-gray-700'"
          class="relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none">
          <span :class="monitor.dns_drift_alert ? 'translate-x-4' : 'translate-x-0.5'"
            class="inline-block h-4 w-4 mt-0.5 transform rounded-full bg-white transition-transform" />
        </button>
      </label>
      <label v-if="monitor.dns_drift_alert" class="flex items-center justify-between cursor-pointer gap-4">
        <div>
          <p class="text-sm text-gray-300">{{ t('monitors.dns_drift.split_horizon') }}</p>
          <p class="text-xs text-gray-500">{{ t('monitors.dns_drift.split_horizon_desc') }}</p>
        </div>
        <button type="button" @click="state.toggleSetting('dns_split_enabled')"
          :class="monitor.dns_split_enabled ? 'bg-emerald-600' : 'bg-gray-700'"
          class="relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none">
          <span :class="monitor.dns_split_enabled ? 'translate-x-4' : 'translate-x-0.5'"
            class="inline-block h-4 w-4 mt-0.5 transform rounded-full bg-white transition-transform" />
        </button>
      </label>
    </div>

    <!-- Baseline section (only when drift alert enabled) -->
    <template v-if="monitor.dns_drift_alert">
      <hr class="border-gray-700 mb-4" />

      <!-- Mode normal : baseline unique -->
      <template v-if="!monitor.dns_split_enabled">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <p class="text-xs text-gray-500 mb-1">{{ t('monitors.dns_drift.baseline_current') }}</p>
            <div v-if="monitor.dns_baseline_ips && monitor.dns_baseline_ips.length" class="flex flex-wrap gap-1">
              <span v-for="ip in monitor.dns_baseline_ips" :key="ip"
                class="font-mono text-xs bg-gray-800 text-emerald-400 px-2 py-0.5 rounded">{{ ip }}</span>
            </div>
            <p v-else class="text-xs text-gray-400 italic">{{ t('monitors.dns_drift.baseline_none') }}</p>
          </div>
          <div class="flex gap-2 flex-shrink-0">
            <button @click="state.acceptBaseline" :disabled="state.baselineLoading.value"
              class="btn-primary text-xs disabled:opacity-50">
              {{ t('monitors.dns_drift.accept_baseline') }}
            </button>
            <button @click="state.resetBaseline('all')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips"
              class="btn-ghost text-xs text-red-400 hover:text-red-300 disabled:opacity-50">
              {{ t('monitors.dns_drift.reset_baseline') }}
            </button>
          </div>
        </div>
      </template>

      <!-- Mode split : deux baselines -->
      <template v-else>
        <!-- Baseline interne -->
        <div class="mb-4">
          <p class="text-xs text-gray-500 mb-1">Baseline — sondes internes</p>
          <div v-if="monitor.dns_baseline_ips_internal?.length" class="flex flex-wrap gap-1 mb-1">
            <span v-for="ip in monitor.dns_baseline_ips_internal" :key="ip"
              class="text-xs font-mono px-2 py-0.5 rounded bg-blue-900/40 text-blue-300">{{ ip }}</span>
          </div>
          <p v-else class="text-xs text-gray-400 italic mb-1">Pas encore apprise — en attente d'un check depuis une sonde interne</p>
          <button @click="state.resetBaseline('internal')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips_internal"
            class="text-xs text-gray-500 hover:text-red-400 disabled:opacity-30">
            {{ t('monitors.dns_drift.reset_baseline') }}
          </button>
        </div>
        <!-- Baseline externe -->
        <div>
          <p class="text-xs text-gray-500 mb-1">Baseline — sondes externes</p>
          <div v-if="monitor.dns_baseline_ips_external?.length" class="flex flex-wrap gap-1 mb-1">
            <span v-for="ip in monitor.dns_baseline_ips_external" :key="ip"
              class="text-xs font-mono px-2 py-0.5 rounded bg-emerald-900/40 text-emerald-300">{{ ip }}</span>
          </div>
          <p v-else class="text-xs text-gray-400 italic mb-1">Pas encore apprise — en attente d'un check depuis une sonde externe</p>
          <button @click="state.resetBaseline('external')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips_external"
            class="text-xs text-gray-500 hover:text-red-400 disabled:opacity-30">
            {{ t('monitors.dns_drift.reset_baseline') }}
          </button>
        </div>
      </template>

      <div v-if="state.baselineMsg.value" class="mt-2 text-xs text-emerald-400">{{ state.baselineMsg.value }}</div>
    </template>
  </div>

  <!-- DNS drift alert suggestion modal -->
  <BaseModal :model-value="state.alertModal.value"
    :title="t('monitor_detail.dns_alert_title')"
    @update:model-value="state.alertModal.value = $event">
    <p class="text-sm text-gray-400 mb-4">
      <i18n-t keypath="monitor_detail.dns_alert_desc" tag="span">
        <template #code><code class="text-emerald-400">any_down</code></template>
      </i18n-t>
    </p>
    <div class="mb-4">
      <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('monitor_detail.dns_alert_channel') }}</label>
      <select v-model="state.alertChannelId.value" class="input w-full">
        <option v-for="ch in state.alertChannels.value" :key="ch.id" :value="ch.id">
          {{ ch.name }} ({{ ch.type }})
        </option>
      </select>
    </div>
    <template #footer>
      <button @click="state.toggleSetting('dns_drift_alert'); state.alertModal.value = false" class="flex-1 text-xs text-gray-500 hover:text-gray-300">
        {{ t('monitor_detail.dns_alert_disable') }}
      </button>
      <button @click="state.createAlertRule" :disabled="state.alertCreating.value || !state.alertChannelId.value" class="flex-1 btn-primary disabled:opacity-50">
        {{ state.alertCreating.value ? t('monitor_detail.dns_alert_creating') : t('monitor_detail.dns_alert_create') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { DnsStateKey } from './injectionKeys'

defineProps({
  monitor: { type: Object, required: true },
  formatTarget: { type: Function, required: true },
  formatDate: { type: Function, required: true },
  probeColor: { type: Function, required: true },
  probeName: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(DnsStateKey, dnsState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(DnsStateKey)

const { t } = useI18n()
</script>
