<template>
  <!-- Incidents card (timeline + list) -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4 gap-3 flex-wrap">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.incidents') }}</h2>
      <div class="flex items-center gap-3">
        <div class="inline-flex rounded-md border border-(--border) overflow-hidden">
          <button
            class="px-2.5 py-1 text-[11px] transition-colors"
            :class="state.viewMode.value === 'timeline' ? 'bg-(--accent-glow) text-(--accent)' : 'text-(--text-3) hover:text-(--text-1)'"
            @click="state.viewMode.value = 'timeline'"
          >
            {{ t('monitor_detail.view_timeline') }}
          </button>
          <button
            class="px-2.5 py-1 text-[11px] transition-colors border-l border-(--border)"
            :class="state.viewMode.value === 'list' ? 'bg-(--accent-glow) text-(--accent)' : 'text-(--text-3) hover:text-(--text-1)'"
            @click="state.viewMode.value = 'list'"
          >
            {{ t('monitor_detail.view_list') }}
          </button>
        </div>
        <button
          :disabled="state.incidents.value.length === 0"
          class="text-xs text-(--text-3) hover:text-(--text-1) disabled:opacity-30 disabled:cursor-not-allowed"
          @click="state.downloadIncidentsCsv"
        >
          {{ t('monitor_detail.export_csv') }}
        </button>
        <button class="text-xs text-(--text-3) hover:text-(--text-1)" @click="state.loadIncidents">
          {{ t('monitor_detail.refresh') }}
        </button>
      </div>
    </div>

    <div
      v-if="state.incidentError.value"
      class="mb-3 px-3 py-2 rounded-lg bg-[color-mix(in_srgb,var(--down)_12%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] text-(--down) text-xs"
    >
      {{ state.incidentError.value }}
    </div>

    <div v-if="state.incidents.value.length === 0" class="text-(--text-3) text-sm text-center py-6">
      {{ t('monitor_detail.no_incidents') }}
    </div>

    <!-- Timeline mode -->
    <div
      v-else-if="state.viewMode.value === 'timeline' && state.timelineLayout.value"
      class="space-y-4"
    >
      <div class="relative rounded-lg bg-(--bg-surface) border border-(--border) px-4 pt-4 pb-8">
        <div class="relative h-12">
          <div class="absolute inset-x-0 top-1/2 h-px bg-(--border)" />
          <button
            v-for="it in state.timelineLayout.value.items"
            :key="it.id"
            type="button"
            :title="state.tooltipFor(it.inc, fmtDateTime)"
            :style="{ left: it.x + '%', width: it.w + '%' }"
            class="absolute top-2 bottom-2 rounded-md transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-(--accent)"
            :class="[
              it.ongoing
                ? 'bg-[color-mix(in_srgb,var(--down)_80%,transparent)] hover:bg-(--down) animate-pulse'
                : 'bg-[color-mix(in_srgb,var(--up)_70%,transparent)] hover:bg-(--up)',
              state.selectedIncidentId.value === it.id
                ? 'ring-2 ring-(--accent) shadow-lg z-10'
                : 'opacity-70 hover:opacity-100',
            ]"
            @click="state.selectIncident(it.id)"
          />
        </div>
        <div class="absolute inset-x-4 bottom-2 h-4 text-[10px] text-(--text-3) pointer-events-none">
          <span
            v-for="(tk, i) in state.timelineLayout.value.ticks"
            :key="i"
            class="absolute -translate-x-1/2 whitespace-nowrap"
            :style="{ left: tk.x + '%' }"
          >{{ tk.label }}</span>
        </div>
      </div>

      <div class="flex items-center gap-4 text-[11px] text-(--text-3) px-1">
        <span class="flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 rounded-sm bg-(--down) animate-pulse" />
          {{ t('incidents.ongoing') }}
        </span>
        <span class="flex items-center gap-1.5">
          <span class="w-2.5 h-2.5 rounded-sm bg-(--up)" />
          {{ t('monitor_detail.resolved') }}
        </span>
        <span class="ml-auto">
          {{ state.incidents.value.length }} {{ t('monitor_detail.incidents').toLowerCase() }}
        </span>
      </div>

      <div
        v-if="state.selectedIncident.value"
        class="rounded-lg border border-(--border) bg-(--bg-surface) p-4"
      >
        <div class="flex items-center gap-3 flex-wrap">
          <span
            class="w-2 h-2 rounded-full flex-shrink-0"
            :class="state.selectedIncident.value.resolved_at ? 'bg-(--up)' : 'bg-(--down) animate-pulse'"
          />
          <div class="flex-1 min-w-0">
            <p class="text-sm text-(--text-1)">
              {{ fmtDateTime(state.selectedIncident.value.started_at) }}
              <span v-if="state.selectedIncident.value.resolved_at" class="text-(--text-3)">
                → {{ fmtDateTime(state.selectedIncident.value.resolved_at) }}
                <span class="ml-1 text-(--text-3)">
                  ({{ Math.round(state.selectedIncident.value.duration_seconds / 60) }} min)
                </span>
              </span>
              <span v-else class="text-(--down) font-medium ml-1">{{ t('incidents.ongoing') }}</span>
            </p>
            <p class="text-xs text-(--text-3) mt-0.5 flex items-center gap-2 flex-wrap">
              <span class="capitalize">{{ state.selectedIncident.value.scope }}</span>
              <span
                v-if="state.selectedIncident.value.trigger_kind && state.selectedIncident.value.trigger_kind !== 'legacy'"
                class="font-mono text-[10px] px-1.5 py-px rounded border border-(--accent-border) bg-(--accent-glow) text-(--accent)"
              >
                {{ state.selectedIncident.value.trigger_kind }}
              </span>
              <span
                v-if="state.selectedIncident.value.trigger_kind === 'quorum_slow' && healthState && healthState.p95_5m != null"
                class="text-(--warn)"
              >
                {{ t('monitor_detail.fleet_p95') }}: {{ healthState.p95_5m.toFixed(0) }} ms
              </span>
            </p>
          </div>
          <button
            v-if="state.selectedIncident.value.resolved_at"
            class="btn-ghost btn-sm flex-shrink-0 flex items-center gap-1.5"
            @click="state.openPostmortem(state.selectedIncident.value)"
          >
            📋 {{ t('monitor_detail.postmortem') }}
          </button>
        </div>

        <div class="mt-4 pt-3 border-t border-(--border) space-y-2">
          <div v-if="state.incidentUpdatesLoading.value" class="text-xs text-(--text-3)">
            {{ t('common.loading') }}
          </div>
          <template v-else>
            <div
              v-for="u in state.incidentUpdates.value"
              :key="u.id"
              class="flex gap-2 text-xs"
            >
              <span class="text-(--text-3) font-mono flex-shrink-0">{{ fmtDateTime(u.created_at) }}</span>
              <span
                :class="{
                  'text-(--warn)': u.status === 'investigating',
                  'text-(--accent)': u.status === 'identified',
                  'text-(--accent)': u.status === 'monitoring',
                  'text-(--up)': u.status === 'resolved',
                }"
                class="font-semibold capitalize flex-shrink-0"
              >{{ u.status }}</span>
              <span class="text-(--text-2) break-words">{{ u.message }}</span>
              <span v-if="!u.is_public" class="text-(--text-3) italic">
                ({{ t('monitor_detail.update_private') }})
              </span>
              <button
                class="text-(--down) ml-auto flex-shrink-0"
                :aria-label="t('common.delete')"
                @click="state.deleteIncidentUpdate(state.selectedIncident.value.id, u.id)"
              >✕</button>
            </div>
            <div v-if="state.incidentUpdates.value.length === 0" class="text-(--text-3) italic text-xs">
              {{ t('monitor_detail.no_updates') }}
            </div>
          </template>

          <div class="pt-2 flex gap-2 flex-wrap">
            <select v-model="state.newUpdate.value.status" :aria-label="t('monitor_detail.update_status')" class="input text-xs flex-shrink-0 w-36">
              <option value="investigating">{{ t('monitor_detail.update_status_investigating') }}</option>
              <option value="identified">{{ t('monitor_detail.update_status_identified') }}</option>
              <option value="monitoring">{{ t('monitor_detail.update_status_monitoring') }}</option>
              <option value="resolved">{{ t('monitor_detail.update_status_resolved') }}</option>
            </select>
            <input
              v-model="state.newUpdate.value.message"
              class="input text-xs flex-1 min-w-[160px]"
              :placeholder="t('monitor_detail.update_placeholder')"
              @keydown.enter="state.postIncidentUpdate(state.selectedIncident.value.id)"
            />
            <label class="flex items-center gap-1 text-xs text-(--text-2) flex-shrink-0">
              <input v-model="state.newUpdate.value.is_public" type="checkbox" class="mr-1" />
              {{ t('monitor_detail.update_public') }}
            </label>
            <button
              class="btn-primary btn-sm flex-shrink-0"
              @click="state.postIncidentUpdate(state.selectedIncident.value.id)"
            >{{ t('monitor_detail.update_post') }}</button>
          </div>
        </div>
      </div>
    </div>

    <!-- List mode (fallback) -->
    <div v-else class="divide-y divide-(--border)">
      <div v-for="inc in state.incidents.value" :key="inc.id" class="py-3 text-sm">
        <div class="flex items-center gap-3">
          <span
            class="w-2 h-2 rounded-full flex-shrink-0"
            :class="inc.resolved_at ? 'bg-(--up)' : 'bg-(--down) animate-pulse'"
          />
          <div class="flex-1 min-w-0">
            <p class="text-(--text-2) text-xs">
              {{ fmtDateTime(inc.started_at) }}
              <span v-if="inc.resolved_at" class="text-(--text-3)">
                → {{ fmtDateTime(inc.resolved_at) }}
                <span class="ml-1 text-(--text-3)">
                  ({{ Math.round(inc.duration_seconds / 60) }} min)
                </span>
              </span>
              <span v-else class="text-(--down) font-medium ml-1">{{ t('incidents.ongoing') }}</span>
            </p>
            <p class="text-xs text-(--text-3) mt-0.5 flex items-center gap-2 flex-wrap">
              <span class="capitalize">{{ inc.scope }}</span>
              <span
                v-if="inc.trigger_kind && inc.trigger_kind !== 'legacy'"
                class="font-mono text-[10px] px-1.5 py-px rounded border border-(--accent-border) bg-(--accent-glow) text-(--accent)"
              >
                {{ inc.trigger_kind }}
              </span>
            </p>
          </div>
          <button
            v-if="inc.resolved_at"
            class="btn-ghost btn-sm flex-shrink-0 flex items-center gap-1.5"
            @click="state.openPostmortem(inc)"
          >
            📋 {{ t('monitor_detail.postmortem') }}
          </button>
          <button
            class="btn-ghost btn-sm flex-shrink-0 flex items-center gap-1"
            @click="state.toggleIncidentUpdates(inc.id)"
          >
            📝 {{ t('monitor_detail.updates') }}
          </button>
        </div>

        <div v-if="state.expandedIncident.value === inc.id" class="mt-3 ml-5 space-y-2">
          <div v-if="state.incidentUpdatesLoading.value" class="text-xs text-(--text-3)">
            {{ t('common.loading') }}
          </div>
          <div v-else>
            <div
              v-for="u in state.incidentUpdates.value"
              :key="u.id"
              class="flex gap-2 text-xs"
            >
              <span class="text-(--text-3) font-mono flex-shrink-0">{{ fmtDateTime(u.created_at) }}</span>
              <span
                :class="{
                  'text-(--warn)': u.status === 'investigating',
                  'text-(--accent)': u.status === 'identified',
                  'text-(--accent)': u.status === 'monitoring',
                  'text-(--up)': u.status === 'resolved',
                }"
                class="font-semibold capitalize flex-shrink-0"
              >{{ u.status }}</span>
              <span class="text-(--text-2) break-words">{{ u.message }}</span>
              <span v-if="!u.is_public" class="text-(--text-3) italic">
                ({{ t('monitor_detail.update_private') }})
              </span>
              <button
                class="text-(--down) ml-auto flex-shrink-0"
                :aria-label="t('common.delete')"
                @click="state.deleteIncidentUpdate(inc.id, u.id)"
              >✕</button>
            </div>
            <div v-if="state.incidentUpdates.value.length === 0" class="text-(--text-3) italic">
              {{ t('monitor_detail.no_updates') }}
            </div>
          </div>
          <div class="mt-2 pt-2 border-t border-(--border) space-y-2">
            <div class="flex gap-2">
              <select v-model="state.newUpdate.value.status" :aria-label="t('monitor_detail.update_status')" class="input text-xs flex-shrink-0 w-36">
                <option value="investigating">{{ t('monitor_detail.update_status_investigating') }}</option>
                <option value="identified">{{ t('monitor_detail.update_status_identified') }}</option>
                <option value="monitoring">{{ t('monitor_detail.update_status_monitoring') }}</option>
                <option value="resolved">{{ t('monitor_detail.update_status_resolved') }}</option>
              </select>
              <input
                v-model="state.newUpdate.value.message"
                class="input text-xs flex-1"
                :placeholder="t('monitor_detail.update_placeholder')"
                @keydown.enter="state.postIncidentUpdate(inc.id)"
              />
              <label class="flex items-center gap-1 text-xs text-(--text-2) flex-shrink-0">
                <input v-model="state.newUpdate.value.is_public" type="checkbox" class="mr-1" />
                {{ t('monitor_detail.update_public') }}
              </label>
              <button
                class="btn-primary btn-sm flex-shrink-0"
                @click="state.postIncidentUpdate(inc.id)"
              >{{ t('monitor_detail.update_post') }}</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Post-mortem modal -->
  <BaseModal :model-value="state.postmortem.value.open" size="xl"
    :title="t('monitor_detail.postmortem')"
    @update:model-value="state.postmortem.value.open = $event">
    <div v-if="state.postmortem.value.loading" class="text-(--text-2) text-sm text-center py-8">
      {{ t('common.loading') }}
    </div>
    <pre v-else class="text-xs text-(--text-2) font-mono whitespace-pre-wrap leading-relaxed">{{ state.postmortem.value.content }}</pre>
    <template #footer>
      <button
        class="btn-primary btn-sm flex items-center gap-1.5 ml-auto"
        @click="state.downloadPostmortem"
      >
        ⬇️ {{ t('monitor_detail.download_postmortem') }}
      </button>
    </template>
  </BaseModal>

  <!-- SLA report -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.sla_report') }}</h2>
    </div>
    <div class="flex flex-wrap gap-3 items-end">
      <div>
        <label for="sla-from" class="text-xs text-(--text-3) block mb-1">{{ t('monitor_detail.sla_from') }}</label>
        <input id="sla-from" v-model="state.slaFrom.value" type="date" class="input text-xs" />
      </div>
      <div>
        <label for="sla-to" class="text-xs text-(--text-3) block mb-1">{{ t('monitor_detail.sla_to') }}</label>
        <input id="sla-to" v-model="state.slaTo.value" type="date" class="input text-xs" />
      </div>
      <button
        :disabled="!state.slaFrom.value || state.slaLoading.value"
        class="btn-primary btn-sm flex items-center gap-2 disabled:opacity-50"
        @click="state.downloadSlaReport"
      >
        <span v-if="state.slaLoading.value" class="animate-spin">⏳</span>
        <span v-else>📊</span>
        {{ t('monitor_detail.sla_generate') }}
      </button>
    </div>
    <div v-if="state.slaResult.value" class="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.sla_uptime') }}</p>
        <p
          class="text-xl font-bold"
          :class="state.slaResult.value.uptime_percent >= 99 ? 'text-(--up)' : 'text-(--down)'"
        >
          {{ state.slaResult.value.uptime_percent?.toFixed(3) }}%
        </p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.sla_incidents') }}</p>
        <p class="text-xl font-bold text-(--text-2)">{{ state.slaResult.value.incident_count }}</p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.sla_downtime') }}</p>
        <p class="text-xl font-bold text-(--text-2)">
          {{ state.slaResult.value.total_downtime_seconds ? Math.round(state.slaResult.value.total_downtime_seconds / 60) + 'm' : '0' }}
        </p>
      </div>
      <div class="bg-(--bg-surface-2) rounded-lg p-3 text-center">
        <p class="text-xs text-(--text-3)">{{ t('monitor_detail.sla_p95') }}</p>
        <p
          class="text-xl font-bold text-(--text-2)"
          :title="state.slaResult.value.p95_is_estimate ? t('monitor_detail.sla_p95_estimate') : null"
        >
          {{ state.slaResult.value.p95_response_time_ms
            ? (state.slaResult.value.p95_is_estimate ? '≈' : '') + Math.round(state.slaResult.value.p95_response_time_ms) + 'ms'
            : '—' }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { IncidentsStateKey } from './injectionKeys'

defineProps({
  healthState: { type: Object, default: null },
  fmtDateTime: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(IncidentsStateKey, incidentsState).
// The injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(IncidentsStateKey)

const { t } = useI18n()
</script>
