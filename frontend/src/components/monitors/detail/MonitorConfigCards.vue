<template>
  <!-- Network scope card (not for heartbeat / composite) -->
  <div v-if="hasNetworkScope" class="card mb-6">
    <h2 class="text-sm font-semibold text-(--text-2) mb-3">{{ t('monitors.network_scope.label') }}</h2>
    <div class="grid grid-cols-3 gap-2">
      <button
        v-for="s in patch.networkScopeOptions.value" :key="s.value" type="button"
        @click="patch.setNetworkScope(s.value)"
        class="py-2 px-2 rounded-lg border text-xs font-medium transition-colors text-center"
        :class="monitor.network_scope === s.value
          ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
          : 'border-(--border) text-(--text-2) hover:border-(--border-hover) hover:text-(--text-1)'"
      >
        <div class="text-base mb-0.5">{{ s.icon }}</div>
        {{ s.label }}
      </button>
    </div>
    <p class="text-xs text-(--text-3) mt-2">{{ patch.networkScopeOptions.value.find(s => s.value === monitor.network_scope)?.desc }}</p>
  </div>

  <!-- Schema drift card -->
  <div v-if="isHttpLike && monitor.schema_drift_enabled" class="card mb-6">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('sweep.schema_drift_title') }}</h2>
      <label class="flex items-center gap-2 cursor-pointer">
        <span class="text-xs text-(--text-2)">{{ t('sweep.enabled') }}</span>
        <input
          type="checkbox"
          :checked="monitor.schema_drift_enabled"
          @change="patch.toggleSchemaDrift($event.target.checked)"
        />
      </label>
    </div>

    <template v-if="monitor.schema_drift_enabled">
      <div class="flex items-start justify-between gap-4">
        <div class="flex-1">
          <p class="text-xs text-(--text-3) mb-1">{{ t('sweep.baseline_fingerprint') }}</p>
          <div v-if="monitor.schema_baseline">
            <code class="font-mono text-xs text-(--up) bg-(--bg-surface-2) px-2 py-1 rounded block">{{ monitor.schema_baseline }}</code>
            <p v-if="monitor.schema_baseline_updated_at" class="text-xs text-(--text-3) mt-1">
              Updated {{ fmtDateTime(monitor.schema_baseline_updated_at) }}
            </p>
          </div>
          <p v-else class="text-xs text-(--text-3) italic">{{ t('sweep.baseline_none') }}</p>
        </div>
        <div class="flex gap-2 flex-shrink-0">
          <button v-if="schemaAlert.wired.value !== true" @click="schemaAlert.offerAlert('schema_drift')" class="btn-secondary btn-sm">{{ t('detection_alert.cta') }}</button>
          <button @click="patch.acceptSchemaBaseline" class="btn-primary btn-sm">{{ t('sweep.accept_latest') }}</button>
          <button @click="patch.resetSchemaBaseline" :disabled="!monitor.schema_baseline" class="btn-ghost btn-sm text-(--down) disabled:opacity-50">{{ t('sweep.reset') }}</button>
        </div>
      </div>

      <!-- Detection ↔ notification state (B-3) -->
      <p v-if="schemaAlert.wired.value !== null" class="text-xs mt-2" :class="schemaAlert.wired.value ? 'text-(--up)' : 'text-(--warn)'">
        {{ schemaAlert.wired.value ? '✓ ' + t('detection_alert.wired') : '⚠ ' + t('detection_alert.unwired') }}
      </p>

      <DetectionAlertBridge
        :open="schemaAlert.alertModal.value"
        :channels="schemaAlert.alertChannels.value"
        :channel-id="schemaAlert.alertChannelId.value"
        :creating="schemaAlert.alertCreating.value"
        @update:channel-id="schemaAlert.alertChannelId.value = $event"
        @create="schemaAlert.createAlertRule"
        @dismiss="schemaAlert.dismiss"
        @close="schemaAlert.dismiss"
      />
    </template>
    <template v-else>
      <p class="text-xs text-(--text-3)">{{ t('sweep.schema_drift_hint') }}</p>
    </template>
  </div>

  <!-- Composite members card -->
  <div v-if="isComposite" class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitors.composite.members') }}</h2>
    </div>
    <div v-if="deps.compositeMembers.value.length" class="space-y-2 mb-4">
      <div v-for="m in deps.compositeMembers.value" :key="m.id"
        class="flex items-center gap-3 px-3 py-2 rounded-lg bg-(--bg-surface-2)">
        <span class="flex-1 text-sm text-(--text-2) font-mono">{{ deps.memberName(m.monitor_id) }}</span>
        <span v-if="m.role" class="text-xs text-(--accent) bg-(--accent-glow) px-2 py-0.5 rounded">{{ m.role }}</span>
        <span class="text-xs text-(--text-3)">×{{ m.weight }}</span>
        <button @click="deps.removeCompositeMember(m.id)"
          class="text-(--down) text-xs ml-2" :aria-label="t('a11y.remove')">✕</button>
      </div>
    </div>
    <p v-else class="text-(--text-3) text-sm mb-4">{{ t('monitors.composite.no_members') }}</p>
    <div class="flex gap-2 items-end flex-wrap">
      <div class="flex-1 min-w-40">
        <label class="text-xs text-(--text-3) block mb-1">{{ t('monitors.composite.add_member') }}</label>
        <select v-model="deps.newMember.value.monitor_id" class="input w-full text-sm">
          <option value="">{{ t('sweep.select_monitor') }}</option>
          <option v-for="m in deps.availableMonitors.value" :key="m.id" :value="m.id">{{ m.name }}</option>
        </select>
      </div>
      <div class="w-32">
        <label class="text-xs text-(--text-3) block mb-1">{{ t('monitors.composite.role_placeholder') }}</label>
        <input v-model="deps.newMember.value.role" class="input w-full text-sm" placeholder="internal" />
      </div>
      <div class="w-20">
        <label class="text-xs text-(--text-3) block mb-1">{{ t('monitors.composite.weight') }}</label>
        <input v-model.number="deps.newMember.value.weight" type="number" min="1" max="100" class="input w-full text-sm" />
      </div>
      <button @click="deps.addCompositeMember" :disabled="!deps.newMember.value.monitor_id" class="btn-primary disabled:opacity-50" :aria-label="t('common.add')">+</button>
    </div>
  </div>

  <!-- Custom request headers (HTTP-like checks) -->
  <div v-if="isHttpLike && monitor.custom_headers && Object.keys(monitor.custom_headers).length" class="card mb-6">
    <h2 class="text-sm font-semibold text-(--text-2) mb-2">{{ t('monitors.customHeaders.title') }}</h2>
    <div class="flex flex-wrap gap-2">
      <span v-for="(val, key) in monitor.custom_headers" :key="key"
            class="text-xs font-mono px-2 py-1 rounded bg-(--bg-surface-2) text-(--text-2) border border-(--border)">
        <span class="text-(--up)">{{ key }}</span>: {{ val }}
      </span>
    </div>
  </div>

  <!-- SSL card (HTTP checks only) -->
  <div v-if="isHttpLike && monitor.ssl_check_enabled && latestSsl" class="card mb-6">
    <div class="flex items-center gap-3 mb-3">
      <ShieldCheck v-if="latestSsl.ssl_valid" class="w-5 h-5 text-(--up)" />
      <ShieldAlert v-else class="w-5 h-5 text-(--down)" />
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('sweep.ssl_certificate') }}</h2>
    </div>
    <div class="grid grid-cols-3 gap-4 text-center">
      <div>
        <p class="text-xs text-(--text-3) mb-1">{{ t('common.status') }}</p>
        <span class="text-sm font-semibold px-2 py-0.5 rounded-full"
          :class="latestSsl.ssl_valid ? 'bg-[color-mix(in_srgb,var(--up)_12%,transparent)] text-(--up)' : 'bg-[color-mix(in_srgb,var(--down)_12%,transparent)] text-(--down)'">
          {{ latestSsl.ssl_valid ? t('sweep.valid') : t('sweep.invalid') }}
        </span>
      </div>
      <div>
        <p class="text-xs text-(--text-3) mb-1">{{ t('sweep.expires_on') }}</p>
        <p class="text-sm font-mono text-(--text-2)">
          {{ latestSsl.ssl_expires_at ? formatDateShort(latestSsl.ssl_expires_at) : '—' }}
        </p>
      </div>
      <div>
        <p class="text-xs text-(--text-3) mb-1">{{ t('sweep.days_remaining') }}</p>
        <p class="text-sm font-bold"
          :class="latestSsl.ssl_days_remaining > monitor.ssl_expiry_warn_days ? 'text-(--up)'
                : latestSsl.ssl_days_remaining > 7 ? 'text-(--warn)' : 'text-(--down)'">
          {{ latestSsl.ssl_days_remaining ?? '—' }}
        </p>
      </div>
    </div>
  </div>
  <div v-else-if="isHttpLike && monitor.ssl_check_enabled && !latestSsl" class="card mb-6">
    <div class="flex items-center gap-2 text-(--text-3) text-sm">
      <Shield class="w-4 h-4" />
      SSL check enabled — waiting for first result
    </div>
  </div>

  <!-- Domain expiry card -->
  <div v-if="isDomainExpiry" class="card mb-6">
    <div class="flex items-center gap-3 mb-3">
      <ShieldCheck v-if="latestDomainExpiry && latestDomainExpiry.ssl_days_remaining > 0" class="w-5 h-5 text-(--up)" />
      <ShieldAlert v-else class="w-5 h-5 text-(--down)" />
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('sweep.domain_expiry') }}</h2>
    </div>
    <div v-if="latestDomainExpiry" class="grid grid-cols-2 gap-4 text-center">
      <div>
        <p class="text-xs text-(--text-3) mb-1">{{ t('sweep.expires_on') }}</p>
        <p class="text-sm font-mono text-(--text-2)">
          {{ latestDomainExpiry.ssl_expires_at ? formatDateShort(latestDomainExpiry.ssl_expires_at) : '—' }}
        </p>
      </div>
      <div>
        <p class="text-xs text-(--text-3) mb-1">{{ t('sweep.days_remaining') }}</p>
        <p class="text-sm font-bold"
          :class="latestDomainExpiry.ssl_days_remaining > 30 ? 'text-(--up)'
                : latestDomainExpiry.ssl_days_remaining > 7 ? 'text-(--warn)' : 'text-(--down)'">
          {{ latestDomainExpiry.ssl_days_remaining ?? '—' }}
        </p>
      </div>
    </div>
    <div v-else class="flex items-center gap-2 text-(--text-3) text-sm">
      <Shield class="w-4 h-4" />
      Waiting for first check result
    </div>
  </div>
</template>

<script setup>
import { computed, inject, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-vue-next'
import { PatchStateKey, DependenciesStateKey } from './injectionKeys'
import { useDetectionAlertBridge } from '../../../composables/useDetectionAlertBridge'
import DetectionAlertBridge from '../../shared/DetectionAlertBridge.vue'

const props = defineProps({
  monitor: { type: Object, required: true },
  results: { type: Array, required: true },
  isHttpLike: { type: Boolean, default: false },
  isComposite: { type: Boolean, default: false },
  isDomainExpiry: { type: Boolean, default: false },
  hasNetworkScope: { type: Boolean, default: false },
  fmtDateTime: { type: Function, required: true },
  formatDateShort: { type: Function, required: true },
})

// Provided by MonitorDetailView (see injectionKeys.js for rationale).
const patch = inject(PatchStateKey)
const deps = inject(DependenciesStateKey)

// Schema drift → notification bridge (same flow as DNS drift), so schema drift
// isn't a detection that silently sends nothing.
const schemaAlert = useDetectionAlertBridge(toRef(props, 'monitor'))

// Check whether a schema_drift alert is already wired, to show the state indicator.
watch(
  () => props.monitor?.schema_drift_enabled && props.monitor?.id,
  (ready) => { if (ready) schemaAlert.refreshWired('schema_drift') },
  { immediate: true },
)

const { t } = useI18n()

const latestSsl = computed(() =>
  props.results.find(r => r.ssl_valid !== null && r.ssl_valid !== undefined) ?? null
)

const latestDomainExpiry = computed(() =>
  props.results.find(r => r.ssl_expires_at !== null && r.ssl_expires_at !== undefined) ?? null
)
</script>
