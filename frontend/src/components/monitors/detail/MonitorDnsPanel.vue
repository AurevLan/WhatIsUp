<template>
  <!-- DNS: value changelog -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.dns_change_history') }}</h2>
      <span class="text-xs text-(--text-3) font-mono bg-(--bg-surface-2) px-2 py-1 rounded">
        {{ monitor.dns_record_type || 'A' }} · {{ formatTarget(monitor) }}
      </span>
    </div>
    <div v-if="state.changelog.value.length" class="space-y-2">
      <div v-for="(entry, i) in state.changelog.value" :key="i"
        class="flex items-start gap-3 py-2 px-3 rounded-lg"
        :class="entry.old_value === null ? 'bg-(--accent-glow)' : 'bg-[color-mix(in_srgb,var(--warn)_10%,transparent)]'"
      >
        <!-- Icon -->
        <span class="text-base mt-0.5 shrink-0">{{ entry.old_value === null ? '🔵' : '🔄' }}</span>

        <!-- Date + probe -->
        <div class="shrink-0 w-36">
          <p class="text-xs text-(--text-2)">{{ formatDate(entry.checked_at) }}</p>
          <p class="text-xs font-medium mt-0.5" :style="`color:${probeColor(entry.probe_id)}`">
            {{ probeName(entry.probe_id) }}
          </p>
        </div>

        <!-- Change arrow -->
        <div class="flex-1 font-mono text-sm">
          <div v-if="entry.old_value !== null" class="flex items-center gap-2 flex-wrap">
            <span class="text-(--down) line-through text-xs">{{ entry.old_value || '(empty)' }}</span>
            <span class="text-(--text-3)">→</span>
            <span :class="entry.new_value ? 'text-(--up)' : 'text-(--text-3)'">
              {{ entry.new_value || '(resolution failed)' }}
            </span>
          </div>
          <div v-else>
            <span class="text-(--accent)">First value: {{ entry.new_value || '—' }}</span>
          </div>
        </div>
      </div>
    </div>
    <p v-else class="text-(--text-3) text-sm text-center py-4">No changes detected in the loaded period</p>
  </div>

  <!-- DNS drift card (always visible for DNS monitors) -->
  <div class="card mb-6">
    <h2 class="text-sm font-semibold text-(--text-2) mb-4">{{ t('monitors.dns_drift.label') }}</h2>

    <!-- Toggles -->
    <div class="space-y-3 mb-4">
      <label class="flex items-center justify-between cursor-pointer gap-4">
        <div>
          <p class="text-sm text-(--text-2)">{{ t('monitors.dns_drift.label') }}</p>
          <p class="text-xs text-(--text-3)">{{ t('monitors.dns_drift.desc') }}</p>
        </div>
        <button type="button" @click="state.toggleSetting('dns_drift_alert')"
          :aria-label="t('monitors.dns_drift.label')"
          :class="monitor.dns_drift_alert ? 'bg-(--up)' : 'bg-(--bg-surface-2)'"
          class="relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none">
          <span :class="monitor.dns_drift_alert ? 'translate-x-4' : 'translate-x-0.5'"
            class="inline-block h-4 w-4 mt-0.5 transform rounded-full bg-white transition-transform" />
        </button>
      </label>
      <label v-if="monitor.dns_drift_alert" class="flex items-center justify-between cursor-pointer gap-4">
        <div>
          <p class="text-sm text-(--text-2)">{{ t('monitors.dns_drift.split_horizon') }}</p>
          <p class="text-xs text-(--text-3)">{{ t('monitors.dns_drift.split_horizon_desc') }}</p>
        </div>
        <button type="button" @click="state.toggleSetting('dns_split_enabled')"
          :aria-label="t('monitors.dns_drift.split_horizon')"
          :class="monitor.dns_split_enabled ? 'bg-(--up)' : 'bg-(--bg-surface-2)'"
          class="relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors focus:outline-none">
          <span :class="monitor.dns_split_enabled ? 'translate-x-4' : 'translate-x-0.5'"
            class="inline-block h-4 w-4 mt-0.5 transform rounded-full bg-white transition-transform" />
        </button>
      </label>
    </div>

    <!-- Baseline section (only when drift alert enabled) -->
    <template v-if="monitor.dns_drift_alert">
      <hr class="border-(--border) mb-4" />

      <!-- Mode normal : baseline unique -->
      <template v-if="!monitor.dns_split_enabled">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <p class="text-xs text-(--text-3) mb-1">{{ t('monitors.dns_drift.baseline_current') }}</p>
            <div v-if="monitor.dns_baseline_ips && monitor.dns_baseline_ips.length" class="flex flex-wrap gap-1">
              <span v-for="ip in monitor.dns_baseline_ips" :key="ip"
                class="font-mono text-xs bg-(--bg-surface-2) text-(--up) px-2 py-0.5 rounded">{{ ip }}</span>
            </div>
            <p v-else class="text-xs text-(--text-2) italic">{{ t('monitors.dns_drift.baseline_none') }}</p>
          </div>
          <div class="flex gap-2 flex-shrink-0">
            <button @click="state.acceptBaseline" :disabled="state.baselineLoading.value"
              class="btn-primary btn-sm disabled:opacity-50">
              {{ t('monitors.dns_drift.accept_baseline') }}
            </button>
            <button @click="state.resetBaseline('all')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips"
              class="btn-ghost btn-sm text-(--down) disabled:opacity-50">
              {{ t('monitors.dns_drift.reset_baseline') }}
            </button>
          </div>
        </div>
      </template>

      <!-- Mode split : deux baselines -->
      <template v-else>
        <!-- Baseline interne -->
        <div class="mb-4">
          <p class="text-xs text-(--text-3) mb-1">Baseline — sondes internes</p>
          <div v-if="monitor.dns_baseline_ips_internal?.length" class="flex flex-wrap gap-1 mb-1">
            <span v-for="ip in monitor.dns_baseline_ips_internal" :key="ip"
              class="text-xs font-mono px-2 py-0.5 rounded bg-(--accent-glow) text-(--accent)">{{ ip }}</span>
          </div>
          <p v-else class="text-xs text-(--text-2) italic mb-1">Pas encore apprise — en attente d'un check depuis une sonde interne</p>
          <button @click="state.resetBaseline('internal')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips_internal"
            class="text-xs text-(--text-3) hover:text-(--down) disabled:opacity-30">
            {{ t('monitors.dns_drift.reset_baseline') }}
          </button>
        </div>
        <!-- Baseline externe -->
        <div>
          <p class="text-xs text-(--text-3) mb-1">Baseline — sondes externes</p>
          <div v-if="monitor.dns_baseline_ips_external?.length" class="flex flex-wrap gap-1 mb-1">
            <span v-for="ip in monitor.dns_baseline_ips_external" :key="ip"
              class="text-xs font-mono px-2 py-0.5 rounded bg-[color-mix(in_srgb,var(--up)_12%,transparent)] text-(--up)">{{ ip }}</span>
          </div>
          <p v-else class="text-xs text-(--text-2) italic mb-1">Pas encore apprise — en attente d'un check depuis une sonde externe</p>
          <button @click="state.resetBaseline('external')" :disabled="state.baselineLoading.value || !monitor.dns_baseline_ips_external"
            class="text-xs text-(--text-3) hover:text-(--down) disabled:opacity-30">
            {{ t('monitors.dns_drift.reset_baseline') }}
          </button>
        </div>
      </template>

      <div v-if="state.baselineMsg.value" class="mt-2 text-xs text-(--up)">{{ state.baselineMsg.value }}</div>
    </template>
  </div>

  <!-- DNS drift → alert suggestion (shared bridge) -->
  <DetectionAlertBridge
    :open="state.alertModal.value"
    :channels="state.alertChannels.value"
    :channel-id="state.alertChannelId.value"
    :creating="state.alertCreating.value"
    :dismiss-label="t('monitor_detail.dns_alert_disable')"
    @update:channel-id="state.alertChannelId.value = $event"
    @create="state.createAlertRule"
    @dismiss="state.toggleSetting('dns_drift_alert'); state.alertModal.value = false"
    @close="state.alertModal.value = false"
  >
    <template #description>
      <i18n-t keypath="monitor_detail.dns_alert_desc" tag="span">
        <template #code><code class="text-(--up)">any_down</code></template>
      </i18n-t>
    </template>
  </DetectionAlertBridge>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import DetectionAlertBridge from '../../shared/DetectionAlertBridge.vue'
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
