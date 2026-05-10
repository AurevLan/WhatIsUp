<template>
  <div class="card">
    <h2 class="text-sm font-semibold text-gray-300 mb-4">{{ t('monitor_detail.recent_checks') }}</h2>
    <table class="w-full text-sm">
      <thead>
        <tr class="text-xs text-gray-500 border-b border-gray-800">
          <th class="pb-2 text-left">{{ t('monitor_detail.col_time') }}</th>
          <th class="pb-2 text-left">{{ t('monitor_detail.col_probe') }}</th>
          <th class="pb-2 text-left">{{ t('common.status') }}</th>
          <th v-if="!noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left">HTTP</th>
          <th class="pb-2 text-left">{{ t('monitor_detail.col_response') }}</th>
          <th v-if="isHttpLike" class="pb-2 text-left hidden xl:table-cell">
            {{ t('monitor_detail.col_waterfall') }}
          </th>
          <th v-if="monitor.check_type === 'scenario'" class="pb-2 text-left">
            {{ t('monitor_detail.col_steps') }}
          </th>
          <th v-if="!noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left hidden md:table-cell">
            {{ t('monitor_detail.col_redirects') }}
          </th>
          <th v-if="monitor.ssl_check_enabled" class="pb-2 text-left hidden lg:table-cell">SSL</th>
          <th v-if="noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left hidden md:table-cell">
            {{ t('monitor_detail.col_error') }}
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-800">
        <tr v-for="r in results.slice(0, 50)" :key="r.id">
          <td class="py-2 text-gray-400 text-xs whitespace-nowrap">{{ formatDate(r.checked_at) }}</td>
          <td class="py-2 text-xs">
            <span class="font-medium" :style="`color:${probeColor(r.probe_id)}`">
              {{ probeName(r.probe_id) }}
            </span>
          </td>
          <td class="py-2">
            <span
              class="text-xs font-medium px-2 py-0.5 rounded-full"
              :class="{
                'bg-emerald-900/50 text-emerald-400': r.status === 'up',
                'bg-red-900/50 text-red-400': r.status === 'down',
                'bg-amber-900/50 text-amber-400': r.status === 'timeout',
                'bg-orange-900/50 text-orange-400': r.status === 'error',
              }"
            >{{ r.status }}</span>
          </td>
          <td v-if="!noHttpTypes.includes(monitor.check_type)" class="py-2 text-gray-300">
            {{ r.http_status ?? '—' }}
          </td>
          <td class="py-2 text-gray-300">
            {{ r.response_time_ms ? Math.round(r.response_time_ms) + 'ms' : '—' }}
          </td>
          <td v-if="isHttpLike" class="py-2 hidden xl:table-cell">
            <div v-if="r.ttfb_ms != null" class="flex items-center gap-1.5 text-xs font-mono min-w-[120px]">
              <div class="flex h-2 rounded overflow-hidden flex-1 bg-gray-800">
                <div
                  class="bg-blue-500/70 h-full"
                  :style="`width:${Math.round((r.dns_resolve_ms || 0) / r.response_time_ms * 100)}%`"
                  title="DNS"
                ></div>
                <div
                  class="bg-amber-500/70 h-full"
                  :style="`width:${Math.round(r.ttfb_ms / r.response_time_ms * 100)}%`"
                  title="TTFB"
                ></div>
                <div class="bg-emerald-500/70 h-full" :style="`flex:1`" title="Download"></div>
              </div>
              <span class="text-gray-500">{{ r.ttfb_ms }}ms</span>
            </div>
            <span v-else class="text-gray-700 text-xs">—</span>
          </td>
          <td v-if="monitor.check_type === 'scenario'" class="py-2 text-xs">
            <span v-if="r.scenario_result">
              <span :class="r.status === 'up' ? 'text-emerald-400' : 'text-red-400'">
                {{ r.scenario_result.steps_passed }}/{{ r.scenario_result.steps_total }}
              </span>
              <span v-if="r.scenario_result.failed_step_label" class="text-gray-500 ml-1">
                · {{ r.scenario_result.failed_step_label }}
              </span>
            </span>
            <span v-else class="text-gray-600">—</span>
          </td>
          <td
            v-if="!noHttpTypes.includes(monitor.check_type)"
            class="py-2 text-gray-400 hidden md:table-cell"
          >{{ r.redirect_count }}</td>
          <td v-if="monitor.ssl_check_enabled" class="py-2 hidden lg:table-cell">
            <span v-if="r.ssl_valid === null || r.ssl_valid === undefined" class="text-gray-600 text-xs">—</span>
            <span v-else-if="r.ssl_valid" class="text-xs text-emerald-400">
              ✓ {{ r.ssl_days_remaining }}{{ t('monitor_detail.days_short') }}
            </span>
            <span v-else class="text-xs text-red-400">✗ {{ t('monitor_detail.ssl_expired') }}</span>
          </td>
          <td
            v-if="noHttpTypes.includes(monitor.check_type)"
            class="py-2 text-xs text-red-300 hidden md:table-cell truncate max-w-xs"
          >{{ r.error_message || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  monitor: { type: Object, required: true },
  results: { type: Array, default: () => [] },
  noHttpTypes: { type: Array, default: () => [] },
  isHttpLike: { type: Boolean, default: false },
  formatDate: { type: Function, required: true },
  probeColor: { type: Function, required: true },
  probeName: { type: Function, required: true },
})

const { t } = useI18n()
</script>
