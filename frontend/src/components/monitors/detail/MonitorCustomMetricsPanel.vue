<template>
  <!-- Métriques custom push -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.custom_metrics') }}</h2>
      <button
        @click="state.showPushUrlModal.value = true"
        class="btn-secondary text-xs"
      >
        {{ t('monitor_detail.push_url') }}
      </button>
    </div>

    <!-- Charts by metric_name -->
    <div v-if="state.names.value.length" class="space-y-6">
      <div v-for="mName in state.names.value" :key="mName">
        <p class="text-xs font-mono text-(--text-2) mb-2">{{ mName }}
          <span v-if="state.unit(mName)" class="text-(--text-3) ml-1">({{ state.unit(mName) }})</span>
        </p>
        <apexchart
          type="line"
          height="160"
          :options="state.options(mName)"
          :series="state.series(mName)"
        />
      </div>
    </div>
    <p v-else class="text-(--text-3) text-sm text-center py-6">
      No metrics pushed yet — use the push URL to send business metrics.
    </p>
  </div>

  <!-- Modal URL de push -->
  <BaseModal :model-value="state.showPushUrlModal.value" size="lg"
    title="URL de push — Métriques custom"
    @update:model-value="state.showPushUrlModal.value = $event">
    <div class="space-y-4">
      <div>
        <p class="text-xs text-(--text-3) mb-1">Endpoint</p>
        <code class="block text-xs font-mono bg-(--bg-surface-2) text-(--accent) px-3 py-2 rounded break-all">
          POST {{ apiBase }}/api/v1/metrics/{{ monitor?.id }}
        </code>
      </div>
      <div>
        <p class="text-xs text-(--text-3) mb-1">Exemple curl</p>
        <pre class="text-xs font-mono bg-(--bg-surface-2) text-(--text-2) px-3 py-2 rounded overflow-x-auto whitespace-pre">curl -X POST \
  {{ apiBase }}/api/v1/metrics/{{ monitor?.id }} \
  -H "Authorization: Bearer &lt;votre_token_jwt&gt;" \
  -H "Content-Type: application/json" \
  -d '{"metric_name":"orders_per_minute","value":42,"unit":"req/min"}'</pre>
      </div>
      <div class="text-xs text-(--text-3)">
        <p>Champs disponibles : <code class="text-(--text-2)">metric_name</code> (requis), <code class="text-(--text-2)">value</code> (requis), <code class="text-(--text-2)">unit</code> (optionnel), <code class="text-(--text-2)">pushed_at</code> (ISO 8601, optionnel).</p>
      </div>
    </div>
  </BaseModal>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { CustomMetricsStateKey } from './injectionKeys'

defineProps({
  monitor: { type: Object, default: null },
  apiBase: { type: String, required: true },
})

// Provided by MonitorDetailView via provide(CustomMetricsStateKey, customMetricsState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(CustomMetricsStateKey)

const { t } = useI18n()
</script>
