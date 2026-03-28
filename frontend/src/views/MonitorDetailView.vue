<template>
  <div class="p-8" v-if="monitor">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <nav class="breadcrumb">
        <router-link to="/monitors" class="breadcrumb__link">{{ t('monitors.title') }}</router-link>
        <span class="breadcrumb__sep">/</span>
        <span class="breadcrumb__current">{{ monitor.name }}</span>
      </nav>
      <div class="flex-1">
        <div class="flex items-center gap-3">
          <span class="w-3 h-3 rounded-full" :class="statusClass"></span>
          <h1 class="text-2xl font-bold text-white">{{ monitor.name }}</h1>
        </div>
        <p class="text-gray-400 text-sm mt-1 font-mono">
          <span class="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500 uppercase mr-2">{{ monitor.check_type }}</span>
          {{ formatTarget(monitor) }}
        </p>
      </div>
    </div>

    <!-- No alert rules banner -->
    <div
      v-if="monitor && alertRulesLoaded && alertRules.length === 0"
      class="mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-amber-800/40 bg-amber-900/20"
    >
      <div class="flex items-center gap-2">
        <span class="text-amber-400 text-lg">⚠</span>
        <span class="text-sm text-amber-300">{{ t('monitors.alert_setup.no_rules_banner') }}</span>
      </div>
      <button
        @click="showAutoAlertModal = true"
        class="btn-primary text-xs whitespace-nowrap"
      >{{ t('monitors.alert_setup.setup_now') }}</button>
    </div>

    <!-- Auto-alert setup modal -->
    <div v-if="showAutoAlertModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
        <h2 class="text-lg font-semibold text-white mb-4">{{ t('monitors.alert_setup.modal_title') }}</h2>
        <div v-if="autoAlertChannels.length === 0" class="text-sm text-gray-400 mb-4">
          {{ t('monitors.alert_setup.no_channels') }}
        </div>
        <div v-else class="space-y-2 mb-4">
          <label
            v-for="ch in autoAlertChannels" :key="ch.id"
            class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
            :class="autoAlertSelectedChannels.includes(ch.id)
              ? 'border-blue-600/60 bg-blue-950/30'
              : 'border-gray-800 hover:border-gray-700'"
          >
            <input type="checkbox" :value="ch.id" v-model="autoAlertSelectedChannels"
              class="rounded bg-gray-800 border-gray-600 text-blue-500" />
            <span class="text-sm text-gray-300">{{ ch.name }}</span>
            <span class="text-xs text-gray-600 ml-auto">{{ ch.type }}</span>
          </label>
        </div>
        <div class="flex gap-3">
          <button @click="showAutoAlertModal = false" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">
            {{ t('common.cancel') }}
          </button>
          <button @click="createAutoAlertRules" :disabled="autoAlertSelectedChannels.length === 0 || autoAlertCreating"
            class="flex-1 btn-primary disabled:opacity-50">
            {{ autoAlertCreating ? t('common.loading') : t('monitors.alert_setup.create_rules') }}
          </button>
        </div>
      </div>
    </div>

    <!-- View tabs -->
    <div class="flex gap-1 mb-6 border-b border-gray-800">
      <button
        v-for="tab in viewTabs" :key="tab"
        @click="setTab(tab)"
        class="px-4 py-2 text-sm font-medium transition-colors"
        :class="activeTab === tab
          ? 'text-blue-400 border-b-2 border-blue-400 -mb-px'
          : 'text-gray-500 hover:text-gray-300'"
      >
        {{ tabLabel(tab) }}
      </button>
    </div>

    <!-- ── Onglet Scénario ───────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_SCENARIO">
      <!-- Stats cards -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div class="card text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_24h') }}</p>
          <p class="text-2xl font-bold mt-1" :class="uptime24?.uptime_percent >= 99 ? 'text-emerald-400' : 'text-red-400'">
            {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
          </p>
        </div>
        <div class="card text-center">
          <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_7d') }}</p>
          <p class="text-2xl font-bold mt-1 text-blue-400">
            {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
          </p>
        </div>
        <div class="card text-center">
          <p class="text-xs text-gray-500">Avg. duration</p>
          <p class="text-2xl font-bold mt-1 text-gray-300">
            {{ uptime24?.avg_response_time_ms ? (uptime24.avg_response_time_ms / 1000).toFixed(1) + 's' : '—' }}
          </p>
        </div>
        <div class="card text-center">
          <p class="text-xs text-gray-500">p95 duration</p>
          <p class="text-2xl font-bold mt-1 text-gray-300">
            {{ uptime24?.p95_response_time_ms ? (uptime24.p95_response_time_ms / 1000).toFixed(1) + 's' : '—' }}
          </p>
        </div>
      </div>

      <!-- Edit scenario link -->
      <div class="flex items-center justify-end mb-3">
        <button
          @click="editingMonitor = monitor"
          class="btn-secondary text-xs flex items-center gap-1.5"
          :title="t('monitor_detail.edit')"
        >
          ⚙ {{ t('monitor_detail.edit') }}
        </button>
      </div>

      <!-- Scenario run history -->
      <div class="card">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.recent_checks') }}</h2>
          <button
            @click="handleTriggerCheck"
            :disabled="testing"
            class="btn-primary text-xs flex items-center gap-2 disabled:opacity-50"
          >
            <template v-if="testing">
              <span class="w-2 h-2 rounded-full bg-blue-400 animate-pulse shrink-0"></span>
              <span v-if="testingState === 'queued'">{{ t('monitor_detail.testing_queued') }}</span>
              <span v-else>{{ t('monitor_detail.testing_running') }} {{ testingElapsed > 0 ? t('monitor_detail.testing_elapsed', { s: testingElapsed }) : '' }}</span>
            </template>
            <template v-else>
              ▶ {{ t('monitor_detail.test_now') }}
            </template>
          </button>
        </div>
        <div v-if="results.length" class="space-y-1">
          <div
            v-for="r in results.slice(0, 30)"
            :key="r.id"
            class="rounded-lg border transition-colors"
            :class="newResultId === r.id
              ? 'border-blue-400/80 bg-blue-900/20 shadow-[0_0_0_2px_rgba(96,165,250,0.15)]'
              : selectedRunId === r.id
                ? 'border-blue-600/60 bg-blue-950/20'
                : 'border-gray-800 hover:border-gray-700 bg-gray-900/30'"
          >
            <!-- Run header row (clickable) -->
            <button
              class="w-full flex items-center gap-3 px-4 py-3 text-left"
              @click="selectedRunId = selectedRunId === r.id ? null : r.id"
            >
              <!-- Status dot -->
              <span class="w-2 h-2 rounded-full shrink-0"
                :class="{
                  'bg-emerald-400': r.status === 'up',
                  'bg-red-500': r.status === 'down',
                  'bg-amber-400': r.status === 'timeout',
                  'bg-orange-500': r.status === 'error',
                }"></span>

              <!-- Date -->
              <span class="text-xs text-gray-400 whitespace-nowrap w-36 shrink-0">{{ formatDate(r.checked_at) }}</span>

              <!-- Probe -->
              <span class="text-xs font-medium shrink-0 w-24 truncate" :style="`color:${probeColor(r.probe_id)}`">
                {{ probeName(r.probe_id) }}
              </span>

              <!-- Status badge -->
              <span class="text-xs font-medium px-2 py-0.5 rounded-full shrink-0"
                :class="{
                  'bg-emerald-900/50 text-emerald-400': r.status === 'up',
                  'bg-red-900/50 text-red-400': r.status === 'down',
                  'bg-amber-900/50 text-amber-400': r.status === 'timeout',
                  'bg-orange-900/50 text-orange-400': r.status === 'error',
                }">{{ r.status }}</span>

              <!-- Steps summary -->
              <span class="text-xs flex-1 text-left" v-if="r.scenario_result">
                <span :class="r.status === 'up' ? 'text-emerald-400' : 'text-red-400'">
                  {{ r.scenario_result.steps_passed }}/{{ r.scenario_result.steps_total }} steps
                </span>
                <span v-if="r.scenario_result.steps_warned > 0" class="text-amber-400 ml-2">
                  ⚠ {{ r.scenario_result.steps_warned }} warning(s)
                </span>
                <span v-if="r.scenario_result.failed_step_label" class="text-gray-500 ml-2">
                  · failed: {{ r.scenario_result.failed_step_label }}
                </span>
              </span>
              <span v-else class="flex-1"></span>

              <!-- Total duration -->
              <span class="text-xs text-gray-500 font-mono shrink-0">
                {{ r.response_time_ms ? (r.response_time_ms / 1000).toFixed(2) + 's' : '—' }}
              </span>

              <!-- Expand chevron -->
              <span class="text-gray-600 text-xs shrink-0 ml-1 transition-transform"
                :class="selectedRunId === r.id ? 'rotate-180' : ''">▾</span>
            </button>

            <!-- Expanded: step detail -->
            <div v-if="selectedRunId === r.id && r.scenario_result?.steps?.length"
              class="px-4 pb-3 pt-1 border-t border-gray-800 space-y-1"
            >
              <!-- Duration bar (proportional widths) -->
              <div class="flex gap-0.5 h-2 rounded overflow-hidden mb-3">
                <div
                  v-for="s in r.scenario_result.steps"
                  :key="s.index"
                  class="rounded-sm"
                  :class="s.status === 'passed' ? 'bg-emerald-600' : s.status === 'warned' ? 'bg-amber-500' : 'bg-red-600'"
                  :style="`flex: ${s.duration_ms || 1}`"
                  :title="`${s.label || s.type}: ${s.duration_ms}ms`"
                ></div>
              </div>

              <template
                v-for="s in r.scenario_result.steps"
                :key="s.index"
              >
                <!-- Group step: section divider -->
                <div v-if="s.type === 'group'" class="col-span-full py-1 mt-2 mb-1 border-t border-gray-700/50">
                  <span class="text-xs font-semibold text-gray-400 uppercase tracking-wider">{{ s.label }}</span>
                </div>

                <!-- Regular step row -->
                <div
                  v-else
                  class="flex items-center gap-3 py-1.5 px-3 rounded"
                  :class="s.status === 'passed'
                    ? 'bg-emerald-950/30'
                    : s.status === 'warned'
                      ? 'bg-amber-950/30'
                      : 'bg-red-950/40'"
                >
                  <span class="text-sm shrink-0"
                    :class="s.status === 'passed'
                      ? 'text-emerald-400'
                      : s.status === 'warned'
                        ? 'text-amber-400'
                        : 'text-red-400'"
                  >
                    {{ s.status === 'warned' ? '⚠' : (s.status === 'passed' ? '✓' : '✗') }}
                  </span>
                  <span class="text-xs text-gray-600 shrink-0 w-5 text-right">{{ s.index + 1 }}</span>
                  <span class="text-xs px-1.5 py-0.5 rounded font-mono shrink-0" :class="stepTypeBadgeClass(s.type)">{{ s.type }}</span>
                  <span class="text-sm text-gray-300 flex-1 truncate">{{ s.label }}</span>
                  <span v-if="s.continue_on_fail" class="text-xs px-1 py-0.5 rounded bg-amber-900/30 text-amber-500 shrink-0">skip on fail</span>
                  <span v-if="s.error" class="text-xs text-red-300 truncate max-w-xs" :title="s.error">{{ s.error }}</span>
                  <span class="text-xs text-gray-500 shrink-0 font-mono">{{ s.duration_ms != null ? s.duration_ms + 'ms' : '' }}</span>
                  <button v-if="s.screenshot"
                    @click.stop="openScreenshot(s.screenshot, s.label || s.type)"
                    class="shrink-0 rounded overflow-hidden border border-gray-700 hover:border-blue-500 transition-colors"
                    title="Voir le screenshot"
                  >
                    <img :src="s.screenshot" class="w-16 h-9 object-cover" />
                  </button>
                </div>
              </template>
            </div>
            <!-- No step detail (legacy results) -->
            <div v-else-if="selectedRunId === r.id && r.scenario_result && !r.scenario_result.steps?.length"
              class="px-4 pb-3 pt-1 border-t border-gray-800 text-xs text-gray-500">
              No detail available for this run.
            </div>

            <!-- Error without scenario_result (unhandled probe exception) -->
            <div v-else-if="selectedRunId === r.id && !r.scenario_result && r.error_message"
              class="px-4 pb-3 pt-2 border-t border-gray-800">
              <p class="text-xs font-semibold text-gray-400 mb-1">Error</p>
              <p class="text-xs text-red-300 font-mono break-all">{{ r.error_message }}</p>
            </div>

            <!-- Core Web Vitals (shown when expanded and vitals available) -->
            <div v-if="selectedRunId === r.id && r.scenario_result?.web_vitals && Object.keys(r.scenario_result.web_vitals).length"
              class="px-4 pb-3 pt-2 border-t border-gray-800"
            >
              <p class="text-xs font-semibold text-gray-400 mb-2">Core Web Vitals</p>
              <div class="flex flex-wrap gap-4">
                <div v-if="r.scenario_result.web_vitals.lcp_ms != null" class="flex items-center gap-1.5">
                  <span class="text-xs text-gray-500 font-mono">LCP</span>
                  <span class="text-xs font-mono font-semibold"
                    :class="r.scenario_result.web_vitals.lcp_ms <= 2500 ? 'text-emerald-400'
                          : r.scenario_result.web_vitals.lcp_ms <= 4000 ? 'text-amber-400'
                          : 'text-red-400'">
                    {{ (r.scenario_result.web_vitals.lcp_ms / 1000).toFixed(2) }}s
                  </span>
                  <span class="text-xs" :title="r.scenario_result.web_vitals.lcp_ms <= 2500 ? 'Bon ≤2.5s' : r.scenario_result.web_vitals.lcp_ms <= 4000 ? 'Moyen ≤4s' : 'Mauvais >4s'">
                    {{ r.scenario_result.web_vitals.lcp_ms <= 2500 ? '✅' : r.scenario_result.web_vitals.lcp_ms <= 4000 ? '⚠️' : '❌' }}
                  </span>
                </div>
                <div v-if="r.scenario_result.web_vitals.cls != null" class="flex items-center gap-1.5">
                  <span class="text-xs text-gray-500 font-mono">CLS</span>
                  <span class="text-xs font-mono font-semibold"
                    :class="r.scenario_result.web_vitals.cls <= 0.1 ? 'text-emerald-400'
                          : r.scenario_result.web_vitals.cls <= 0.25 ? 'text-amber-400'
                          : 'text-red-400'">
                    {{ r.scenario_result.web_vitals.cls.toFixed(3) }}
                  </span>
                  <span class="text-xs" :title="r.scenario_result.web_vitals.cls <= 0.1 ? 'Bon ≤0.1' : r.scenario_result.web_vitals.cls <= 0.25 ? 'Moyen ≤0.25' : 'Mauvais >0.25'">
                    {{ r.scenario_result.web_vitals.cls <= 0.1 ? '✅' : r.scenario_result.web_vitals.cls <= 0.25 ? '⚠️' : '❌' }}
                  </span>
                </div>
                <div v-if="r.scenario_result.web_vitals.inp_ms != null" class="flex items-center gap-1.5">
                  <span class="text-xs text-gray-500 font-mono">INP</span>
                  <span class="text-xs font-mono font-semibold"
                    :class="r.scenario_result.web_vitals.inp_ms <= 200 ? 'text-emerald-400'
                          : r.scenario_result.web_vitals.inp_ms <= 500 ? 'text-amber-400'
                          : 'text-red-400'">
                    {{ r.scenario_result.web_vitals.inp_ms }}ms
                  </span>
                  <span class="text-xs" :title="r.scenario_result.web_vitals.inp_ms <= 200 ? 'Bon ≤200ms' : r.scenario_result.web_vitals.inp_ms <= 500 ? 'Moyen ≤500ms' : 'Mauvais >500ms'">
                    {{ r.scenario_result.web_vitals.inp_ms <= 200 ? '✅' : r.scenario_result.web_vitals.inp_ms <= 500 ? '⚠️' : '❌' }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
        <p v-else class="text-gray-500 text-sm text-center py-6">No data yet</p>
      </div>
    </div>

    <!-- ── Disponibilité + Temps de réponse + Checks ─────────────────────── -->
    <div v-if="activeTab === TAB_AVAILABILITY">

    <!-- Stats cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_24h') }}</p>
        <p class="text-2xl font-bold mt-1" :class="uptime24?.uptime_percent >= 99 ? 'text-emerald-400' : 'text-red-400'">
          {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_7d') }}</p>
        <p class="text-2xl font-bold mt-1 text-blue-400">
          {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
      </div>
      <div class="card text-center">
        <!-- DNS: changements ; autres: temps de réponse -->
        <template v-if="monitor.check_type === 'dns'">
          <p class="text-xs text-gray-500">Changes detected</p>
          <p class="text-2xl font-bold mt-1" :class="dnsChangelog.length > 0 ? 'text-amber-400' : 'text-emerald-400'">
            {{ dnsChangelog.length }}
          </p>
        </template>
        <template v-else>
          <p class="text-xs text-gray-500">{{ monitor.check_type === 'tcp' ? 'Avg. latency' : 'Avg. response' }}</p>
          <p class="text-2xl font-bold mt-1 text-gray-300">
            {{ uptime24?.avg_response_time_ms ? Math.round(uptime24.avg_response_time_ms) + 'ms' : '—' }}
          </p>
        </template>
      </div>
      <div class="card text-center">
        <template v-if="monitor.check_type === 'dns'">
          <p class="text-xs text-gray-500">Last change</p>
          <p class="text-sm font-bold mt-1 text-gray-300">
            {{ dnsChangelog[0] ? formatDateShort(dnsChangelog[0].checked_at) : '—' }}
          </p>
        </template>
        <template v-else>
          <p class="text-xs text-gray-500">p95 response</p>
          <p class="text-2xl font-bold mt-1 text-gray-300">
            {{ uptime24?.p95_response_time_ms ? Math.round(uptime24.p95_response_time_ms) + 'ms' : '—' }}
          </p>
        </template>
      </div>
      <div v-if="responseTrend" class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.response_time_trend') }}</p>
        <p class="text-2xl font-bold mt-1" :class="responseTrend.up ? 'text-red-400' : 'text-emerald-400'">
          {{ responseTrend.up ? '↑' : '↓' }} {{ responseTrend.pct }}%
        </p>
        <p class="text-xs text-gray-600 mt-0.5">vs prev. 6h</p>
      </div>
    </div>

    <!-- DNS: current resolved value banner -->
    <div v-if="monitor.check_type === 'dns'" class="card mb-6 flex flex-wrap items-center gap-4">
      <div class="flex items-center gap-2 shrink-0">
        <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">{{ monitor.dns_record_type || 'A' }}</span>
        <span class="text-xs text-gray-600">·</span>
        <span class="text-xs font-mono text-gray-400">{{ formatTarget(monitor) }}</span>
      </div>
      <div class="flex-1 min-w-0">
        <template v-if="currentDnsValues">
          <div class="flex flex-wrap gap-1.5">
            <span
              v-for="v in currentDnsValues" :key="v"
              class="font-mono text-xs px-2 py-0.5 rounded bg-emerald-900/40 text-emerald-300 border border-emerald-800/60"
            >{{ v }}</span>
          </div>
        </template>
        <span v-else class="text-xs text-gray-500 italic">No resolution data yet</span>
      </div>
      <div v-if="monitor.dns_expected_value" class="shrink-0 text-xs font-mono px-2 py-1 rounded bg-blue-900/30 text-blue-300 border border-blue-800/50">
        expected: {{ monitor.dns_expected_value }}
      </div>
    </div>

    <!-- Annual uptime heatmap -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.heatmap_title') }}</h2>
        <span class="text-xs text-gray-500">365 {{ t('common.days') }}</span>
      </div>
      <UptimeHeatmap :monitor-id="String(monitor.id)" />
    </div>

    <!-- DNS: value changelog -->
    <div v-if="monitor.check_type === 'dns'" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">Value change history</h2>
        <span class="text-xs text-gray-500 font-mono bg-gray-800 px-2 py-1 rounded">
          {{ monitor.dns_record_type || 'A' }} · {{ formatTarget(monitor) }}
        </span>
      </div>
      <div v-if="dnsChangelog.length" class="space-y-2">
        <div v-for="(entry, i) in dnsChangelog" :key="i"
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
    <div v-if="monitor.check_type === 'dns'" class="card mb-6">
      <h2 class="text-sm font-semibold text-gray-300 mb-4">{{ t('monitors.dns_drift.label') }}</h2>

      <!-- Toggles -->
      <div class="space-y-3 mb-4">
        <label class="flex items-center justify-between cursor-pointer gap-4">
          <div>
            <p class="text-sm text-gray-300">{{ t('monitors.dns_drift.label') }}</p>
            <p class="text-xs text-gray-500">{{ t('monitors.dns_drift.desc') }}</p>
          </div>
          <button type="button" @click="toggleDnsSetting('dns_drift_alert')"
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
          <button type="button" @click="toggleDnsSetting('dns_split_enabled')"
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
              <button @click="acceptDnsBaseline" :disabled="dnsBaselineLoading"
                class="btn-primary text-xs disabled:opacity-50">
                {{ t('monitors.dns_drift.accept_baseline') }}
              </button>
              <button @click="resetDnsBaseline('all')" :disabled="dnsBaselineLoading || !monitor.dns_baseline_ips"
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
            <button @click="resetDnsBaseline('internal')" :disabled="dnsBaselineLoading || !monitor.dns_baseline_ips_internal"
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
            <button @click="resetDnsBaseline('external')" :disabled="dnsBaselineLoading || !monitor.dns_baseline_ips_external"
              class="text-xs text-gray-500 hover:text-red-400 disabled:opacity-30">
              {{ t('monitors.dns_drift.reset_baseline') }}
            </button>
          </div>
        </template>

        <div v-if="dnsBaselineMsg" class="mt-2 text-xs text-emerald-400">{{ dnsBaselineMsg }}</div>
      </template>
    </div>

    <!-- Network scope card (not for heartbeat / composite) -->
    <div v-if="!['heartbeat', 'composite'].includes(monitor.check_type)" class="card mb-6">
      <h2 class="text-sm font-semibold text-gray-300 mb-3">{{ t('monitors.network_scope.label') }}</h2>
      <div class="grid grid-cols-3 gap-2">
        <button
          v-for="s in networkScopeOptions" :key="s.value" type="button"
          @click="setNetworkScope(s.value)"
          class="py-2 px-2 rounded-lg border text-xs font-medium transition-colors text-center"
          :class="monitor.network_scope === s.value
            ? 'bg-blue-600 border-blue-500 text-white'
            : 'border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300'"
        >
          <div class="text-base mb-0.5">{{ s.icon }}</div>
          {{ s.label }}
        </button>
      </div>
      <p class="text-xs text-gray-500 mt-2">{{ networkScopeOptions.find(s => s.value === monitor.network_scope)?.desc }}</p>
    </div>

    <!-- Schema drift card -->
    <div v-if="['http', 'keyword', 'json_path'].includes(monitor.check_type)" class="card mb-6">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-sm font-semibold text-gray-300">API Schema Drift Detection</h2>
        <label class="flex items-center gap-2 cursor-pointer">
          <span class="text-xs text-gray-400">Enabled</span>
          <input
            type="checkbox"
            :checked="monitor.schema_drift_enabled"
            @change="toggleSchemaDrift($event.target.checked)"
          />
        </label>
      </div>

      <template v-if="monitor.schema_drift_enabled">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1">
            <p class="text-xs text-gray-500 mb-1">Current baseline fingerprint</p>
            <div v-if="monitor.schema_baseline">
              <code class="font-mono text-xs text-emerald-400 bg-gray-800 px-2 py-1 rounded block">{{ monitor.schema_baseline }}</code>
              <p v-if="monitor.schema_baseline_updated_at" class="text-xs text-gray-600 mt-1">
                Updated {{ new Date(monitor.schema_baseline_updated_at).toLocaleString() }}
              </p>
            </div>
            <p v-else class="text-xs text-gray-500 italic">No baseline set — next successful check will auto-set it</p>
          </div>
          <div class="flex gap-2 flex-shrink-0">
            <button @click="acceptSchemaBaseline" class="btn-primary text-xs">Accept latest</button>
            <button @click="resetSchemaBaseline" :disabled="!monitor.schema_baseline" class="btn-ghost text-xs text-red-400 hover:text-red-300 disabled:opacity-50">Reset</button>
          </div>
        </div>
      </template>
      <template v-else>
        <p class="text-xs text-gray-500">Enable to automatically detect JSON response structure changes.</p>
      </template>
    </div>

    <!-- Composite members card -->
    <div v-if="monitor.check_type === 'composite'" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitors.composite.members') }}</h2>
      </div>
      <div v-if="compositeMembers.length" class="space-y-2 mb-4">
        <div v-for="m in compositeMembers" :key="m.id"
          class="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-800/50">
          <span class="flex-1 text-sm text-gray-300 font-mono">{{ memberName(m.monitor_id) }}</span>
          <span v-if="m.role" class="text-xs text-blue-400 bg-blue-950/50 px-2 py-0.5 rounded">{{ m.role }}</span>
          <span class="text-xs text-gray-500">×{{ m.weight }}</span>
          <button @click="removeCompositeMember(m.id)"
            class="text-red-500 hover:text-red-400 text-xs ml-2">✕</button>
        </div>
      </div>
      <p v-else class="text-gray-500 text-sm mb-4">{{ t('monitors.composite.no_members') }}</p>
      <div class="flex gap-2 items-end flex-wrap">
        <div class="flex-1 min-w-40">
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitors.composite.add_member') }}</label>
          <select v-model="newMember.monitor_id" class="input w-full text-sm">
            <option value="">— select a monitor —</option>
            <option v-for="m in availableMonitors" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
        </div>
        <div class="w-32">
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitors.composite.role_placeholder') }}</label>
          <input v-model="newMember.role" class="input w-full text-sm" placeholder="internal" />
        </div>
        <div class="w-20">
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitors.composite.weight') }}</label>
          <input v-model.number="newMember.weight" type="number" min="1" max="100" class="input w-full text-sm" />
        </div>
        <button @click="addCompositeMember" :disabled="!newMember.monitor_id" class="btn-primary text-sm h-9 disabled:opacity-50">+</button>
      </div>
    </div>

    <!-- SSL card (HTTP checks only) -->
    <div v-if="['http', 'keyword', 'json_path'].includes(monitor.check_type) && monitor.ssl_check_enabled && latestSsl" class="card mb-6">
      <div class="flex items-center gap-3 mb-3">
        <ShieldCheck v-if="latestSsl.ssl_valid" class="w-5 h-5 text-emerald-400" />
        <ShieldAlert v-else class="w-5 h-5 text-red-400" />
        <h2 class="text-sm font-semibold text-gray-300">Certificat SSL</h2>
      </div>
      <div class="grid grid-cols-3 gap-4 text-center">
        <div>
          <p class="text-xs text-gray-500 mb-1">{{ t('common.status') }}</p>
          <span class="text-sm font-semibold px-2 py-0.5 rounded-full"
            :class="latestSsl.ssl_valid ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
            {{ latestSsl.ssl_valid ? 'Valid' : 'Invalid' }}
          </span>
        </div>
        <div>
          <p class="text-xs text-gray-500 mb-1">Expires on</p>
          <p class="text-sm font-mono text-gray-300">
            {{ latestSsl.ssl_expires_at ? formatDateShort(latestSsl.ssl_expires_at) : '—' }}
          </p>
        </div>
        <div>
          <p class="text-xs text-gray-500 mb-1">Days remaining</p>
          <p class="text-sm font-bold"
            :class="latestSsl.ssl_days_remaining > monitor.ssl_expiry_warn_days ? 'text-emerald-400'
                  : latestSsl.ssl_days_remaining > 7 ? 'text-amber-400' : 'text-red-400'">
            {{ latestSsl.ssl_days_remaining ?? '—' }}
          </p>
        </div>
      </div>
    </div>
    <div v-else-if="['http', 'keyword', 'json_path'].includes(monitor.check_type) && monitor.ssl_check_enabled && !latestSsl" class="card mb-6">
      <div class="flex items-center gap-2 text-gray-500 text-sm">
        <Shield class="w-4 h-4" />
        SSL check enabled — waiting for first result
      </div>
    </div>

    <!-- Domain expiry card -->
    <div v-if="monitor.check_type === 'domain_expiry'" class="card mb-6">
      <div class="flex items-center gap-3 mb-3">
        <ShieldCheck v-if="latestDomainExpiry && latestDomainExpiry.ssl_days_remaining > 0" class="w-5 h-5 text-emerald-400" />
        <ShieldAlert v-else class="w-5 h-5 text-red-400" />
        <h2 class="text-sm font-semibold text-gray-300">Domain expiry</h2>
      </div>
      <div v-if="latestDomainExpiry" class="grid grid-cols-2 gap-4 text-center">
        <div>
          <p class="text-xs text-gray-500 mb-1">Expires on</p>
          <p class="text-sm font-mono text-gray-300">
            {{ latestDomainExpiry.ssl_expires_at ? formatDateShort(latestDomainExpiry.ssl_expires_at) : '—' }}
          </p>
        </div>
        <div>
          <p class="text-xs text-gray-500 mb-1">Days remaining</p>
          <p class="text-sm font-bold"
            :class="latestDomainExpiry.ssl_days_remaining > 30 ? 'text-emerald-400'
                  : latestDomainExpiry.ssl_days_remaining > 7 ? 'text-amber-400' : 'text-red-400'">
            {{ latestDomainExpiry.ssl_days_remaining ?? '—' }}
          </p>
        </div>
      </div>
      <div v-else class="flex items-center gap-2 text-gray-500 text-sm">
        <Shield class="w-4 h-4" />
        Waiting for first check result
      </div>
    </div>

    <!-- Incidents récents -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.incidents') }}</h2>
        <div class="flex items-center gap-3">
          <button @click="downloadIncidentsCsv" :disabled="incidents.length === 0"
            class="text-xs text-gray-500 hover:text-gray-300 disabled:opacity-30 disabled:cursor-not-allowed">
            {{ t('monitor_detail.export_csv') }}
          </button>
          <button @click="loadIncidents" class="text-xs text-gray-500 hover:text-gray-300">Refresh</button>
        </div>
      </div>
      <div v-if="incidentError" class="mb-3 px-3 py-2 rounded-lg bg-red-900/50 border border-red-700 text-red-300 text-xs">
        {{ incidentError }}
      </div>
      <div v-if="incidents.length === 0" class="text-gray-600 text-sm text-center py-4">{{ t('monitor_detail.no_incidents') }}</div>
      <div v-else class="divide-y divide-gray-800">
        <div v-for="inc in incidents" :key="inc.id" class="py-3 text-sm">
          <div class="flex items-center gap-3">
            <span class="w-2 h-2 rounded-full flex-shrink-0"
              :class="inc.resolved_at ? 'bg-emerald-500' : 'bg-red-500 animate-pulse'" />
            <div class="flex-1 min-w-0">
              <p class="text-gray-300 text-xs">
                {{ new Date(inc.started_at).toLocaleString(locale.value) }}
                <span v-if="inc.resolved_at" class="text-gray-500">
                  → {{ new Date(inc.resolved_at).toLocaleString(locale.value) }}
                  <span class="ml-1 text-gray-600">({{ Math.round(inc.duration_seconds / 60) }} min)</span>
                </span>
                <span v-else class="text-red-400 font-medium ml-1">{{ t('incidents.ongoing') }}</span>
              </p>
              <p class="text-xs text-gray-600 mt-0.5 capitalize">{{ inc.scope }}</p>
            </div>
            <button v-if="inc.resolved_at"
              @click="openPostmortem(inc)"
              class="btn-ghost text-xs flex-shrink-0 flex items-center gap-1.5">
              📋 {{ t('monitor_detail.postmortem') }}
            </button>
            <button
              @click="toggleIncidentUpdates(inc.id)"
              class="btn-ghost text-xs flex-shrink-0 flex items-center gap-1"
            >
              📝 Updates
            </button>
          </div>

          <!-- Incident updates panel -->
          <div v-if="expandedIncident === inc.id" class="mt-3 ml-5 space-y-2">
            <div v-if="incidentUpdatesLoading" class="text-xs text-gray-500">Loading…</div>
            <div v-else>
              <div
                v-for="u in incidentUpdates"
                :key="u.id"
                class="flex gap-2 text-xs"
              >
                <span class="text-gray-600 font-mono flex-shrink-0">{{ new Date(u.created_at).toLocaleString(locale.value) }}</span>
                <span :class="{
                  'text-amber-400': u.status === 'investigating',
                  'text-blue-400': u.status === 'identified',
                  'text-purple-400': u.status === 'monitoring',
                  'text-emerald-400': u.status === 'resolved',
                }" class="font-semibold capitalize flex-shrink-0">{{ u.status }}</span>
                <span class="text-gray-300 break-words">{{ u.message }}</span>
                <span v-if="!u.is_public" class="text-gray-600 italic">(private)</span>
                <button @click="deleteIncidentUpdate(inc.id, u.id)" class="text-red-500 hover:text-red-400 ml-auto flex-shrink-0">✕</button>
              </div>
              <div v-if="incidentUpdates.length === 0" class="text-gray-600 italic">No updates yet</div>
            </div>

            <!-- Add update form -->
            <div class="mt-2 pt-2 border-t border-gray-800 space-y-2">
              <div class="flex gap-2">
                <select v-model="newUpdate.status" class="input text-xs flex-shrink-0 w-36">
                  <option value="investigating">Investigating</option>
                  <option value="identified">Identified</option>
                  <option value="monitoring">Monitoring</option>
                  <option value="resolved">Resolved</option>
                </select>
                <input v-model="newUpdate.message" class="input text-xs flex-1" placeholder="Status update message…" @keydown.enter="postIncidentUpdate(inc.id)" />
                <label class="flex items-center gap-1 text-xs text-gray-400 flex-shrink-0">
                  <input v-model="newUpdate.is_public" type="checkbox" class="mr-1" checked />
                  Public
                </label>
                <button @click="postIncidentUpdate(inc.id)" class="btn-primary text-xs flex-shrink-0">Post</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Modal Post-mortem -->
    <div v-if="postmortem.open"
      class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      @click.self="postmortem.open = false">
      <div class="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-3xl max-h-[85vh] flex flex-col shadow-2xl">
        <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 class="text-sm font-semibold text-white">{{ t('monitor_detail.postmortem') }}</h3>
          <div class="flex items-center gap-2">
            <button @click="downloadPostmortem"
              class="btn-primary text-xs flex items-center gap-1.5">
              ⬇️ {{ t('monitor_detail.download_postmortem') }}
            </button>
            <button @click="postmortem.open = false" class="text-gray-500 hover:text-white text-lg leading-none px-1">✕</button>
          </div>
        </div>
        <div class="overflow-auto flex-1 p-5">
          <div v-if="postmortem.loading" class="text-gray-400 text-sm text-center py-8">{{ t('common.loading') }}</div>
          <pre v-else class="text-xs text-gray-300 font-mono whitespace-pre-wrap leading-relaxed">{{ postmortem.content }}</pre>
        </div>
      </div>
    </div>

    <!-- SLA Report -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.sla_report') }}</h2>
      </div>
      <div class="flex flex-wrap gap-3 items-end">
        <div>
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.sla_from') }}</label>
          <input v-model="slaFrom" type="date" class="input text-xs" />
        </div>
        <div>
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.sla_to') }}</label>
          <input v-model="slaTo" type="date" class="input text-xs" />
        </div>
        <button @click="downloadSlaReport" :disabled="!slaFrom || slaLoading"
          class="btn-primary text-xs h-9 flex items-center gap-2 disabled:opacity-50">
          <span v-if="slaLoading" class="animate-spin">⏳</span>
          <span v-else>📊</span>
          {{ t('monitor_detail.sla_generate') }}
        </button>
      </div>
      <div v-if="slaResult" class="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">Uptime</p>
          <p class="text-xl font-bold" :class="slaResult.uptime_percent >= 99 ? 'text-emerald-400' : 'text-red-400'">
            {{ slaResult.uptime_percent?.toFixed(3) }}%
          </p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">Incidents</p>
          <p class="text-xl font-bold text-gray-300">{{ slaResult.incident_count }}</p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">Downtime total</p>
          <p class="text-xl font-bold text-gray-300">
            {{ slaResult.total_downtime_seconds ? Math.round(slaResult.total_downtime_seconds / 60) + 'm' : '0' }}
          </p>
        </div>
        <div class="bg-gray-800/40 rounded-lg p-3 text-center">
          <p class="text-xs text-gray-500">P95</p>
          <p class="text-xl font-bold text-gray-300">
            {{ slaResult.p95_response_time_ms ? Math.round(slaResult.p95_response_time_ms) + 'ms' : '—' }}
          </p>
        </div>
      </div>
    </div>

    <!-- Chart window selector (shared by availability + RT charts) -->
    <div class="flex items-center gap-1 mb-3">
      <button
        v-for="w in CHART_WINDOWS" :key="w.h"
        @click="chartWindow = w.h"
        class="px-2.5 py-1 text-xs rounded-md border transition-colors"
        :class="chartWindow === w.h
          ? 'bg-blue-600 border-blue-500 text-white'
          : 'border-gray-700 text-gray-500 hover:border-gray-600 hover:text-gray-300'"
      >{{ w.label }}</button>
    </div>

    <!-- Availability timeline -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.availability') }}</h2>
        <span class="text-xs text-gray-500">{{ chartBucketMin(chartWindow) }}min {{ t('monitor_detail.buckets') }}</span>
      </div>
      <apexchart
        v-if="availSeries[0]?.data?.length"
        type="bar"
        height="140"
        :options="availOptions"
        :series="availSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">{{ t('monitor_detail.no_data') }}</p>
    </div>

    <!-- Response time per probe (HTTP/TCP/Keyword/JSON only — not DNS) -->
    <div v-if="monitor.check_type !== 'dns'" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">
          {{ monitor.check_type === 'tcp' ? t('monitor_detail.tcp_latency') : t('monitor_detail.response_time') }}
        </h2>
        <div class="flex items-center gap-3 flex-wrap">
          <span v-if="responseTrend" class="flex items-center gap-1 text-xs font-medium"
            :class="responseTrend.up ? 'text-red-400' : 'text-emerald-400'">
            {{ responseTrend.up ? '↑' : '↓' }} {{ responseTrend.pct }}% {{ t('monitor_detail.trend_vs_6h') }}
          </span>
          <span v-for="(s, i) in rtSeries" :key="s.name" class="flex items-center gap-1.5 text-xs text-gray-400">
            <span class="w-3 h-1.5 rounded-full inline-block" :style="`background:${probeColors[i % probeColors.length]}`" />
            {{ s.name }}
          </span>
        </div>
      </div>
      <apexchart
        v-if="rtSeries.length"
        type="line"
        height="220"
        :options="rtOptions"
        :series="rtSeries"
      />
      <p v-else class="text-gray-500 text-sm text-center py-6">No data yet</p>
    </div>

    <!-- SLO / Error Budget (visible if slo_target is set OR if editing) -->
    <div v-if="monitor.slo_target != null || sloEditing" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.slo_title') }}</h2>
        <div class="flex items-center gap-3">
          <span v-if="monitor.slo_target != null" class="text-xs font-mono" :class="{
            'text-emerald-400': sloData?.status === 'healthy',
            'text-amber-400': sloData?.status === 'at_risk',
            'text-red-400': sloData?.status === 'critical' || sloData?.status === 'exhausted',
            'text-gray-400': !sloData,
          }">
            {{ sloData ? sloData.status.toUpperCase() : '…' }}
          </span>
          <button @click="sloEditing = !sloEditing" class="btn-ghost text-xs">
            ⚙ {{ t('monitor_detail.slo_configure') }}
          </button>
        </div>
      </div>
      <div v-if="monitor.slo_target != null && sloData" class="space-y-4">
        <!-- Stats grid -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="bg-gray-800/40 rounded-lg p-3 text-center">
            <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_objective') }}</p>
            <p class="text-xl font-bold text-blue-400">{{ monitor.slo_target }}%</p>
            <p class="text-xs text-gray-600">{{ monitor.slo_window_days }}d</p>
          </div>
          <div class="bg-gray-800/40 rounded-lg p-3 text-center">
            <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_actual_uptime') }}</p>
            <p class="text-xl font-bold" :class="sloData.uptime_pct >= monitor.slo_target ? 'text-emerald-400' : 'text-red-400'">
              {{ sloData.uptime_pct?.toFixed(3) }}%
            </p>
          </div>
          <div class="bg-gray-800/40 rounded-lg p-3 text-center">
            <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_budget_remaining') }}</p>
            <p class="text-xl font-bold" :class="sloData.error_budget_remaining_minutes >= 0 ? 'text-emerald-400' : 'text-red-400'">
              {{ sloData.error_budget_remaining_minutes >= 0 ? '+' : '' }}{{ sloData.error_budget_remaining_minutes.toFixed(1) }}min
            </p>
          </div>
          <div class="bg-gray-800/40 rounded-lg p-3 text-center">
            <p class="text-xs text-gray-500">{{ t('monitor_detail.slo_burn_rate') }}</p>
            <p class="text-xl font-bold" :class="{
              'text-emerald-400': sloData.burn_rate <= 0.5,
              'text-amber-400': sloData.burn_rate > 0.5 && sloData.burn_rate <= 0.8,
              'text-red-400': sloData.burn_rate > 0.8,
            }">{{ (sloData.burn_rate * 100).toFixed(1) }}%</p>
          </div>
        </div>
        <!-- Error budget progress bar -->
        <div>
          <div class="flex items-center justify-between mb-1.5 text-xs text-gray-500">
            <span>Error budget used</span>
            <span>{{ sloData.error_budget_used_minutes.toFixed(1) }}min / {{ sloData.error_budget_total_minutes.toFixed(1) }}min</span>
          </div>
          <div class="w-full h-2.5 bg-gray-700 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all"
              :class="{
                'bg-emerald-500': sloData.burn_rate <= 0.5,
                'bg-amber-500': sloData.burn_rate > 0.5 && sloData.burn_rate <= 0.8,
                'bg-red-500': sloData.burn_rate > 0.8,
              }"
              :style="`width: ${Math.min(sloData.burn_rate * 100, 100)}%`"
            ></div>
          </div>
        </div>
      </div>
      <p v-else-if="monitor.slo_target != null && !sloData" class="text-gray-500 text-sm text-center py-4">{{ t('common.loading') }}</p>
      <!-- SLO edit form -->
      <div v-if="sloEditing" class="mt-4 p-3 bg-gray-800/60 rounded-lg border border-gray-700 flex flex-wrap items-end gap-3">
        <div>
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.slo_target') }}</label>
          <input v-model.number="sloEditTarget" type="number" min="0" max="100" step="0.1"
            class="input w-32 text-sm" placeholder="99.9" />
        </div>
        <div>
          <label class="text-xs text-gray-500 block mb-1">{{ t('monitor_detail.slo_window') }}</label>
          <input v-model.number="sloEditDays" type="number" min="1" max="365"
            class="input w-24 text-sm" placeholder="30" />
        </div>
        <button @click="saveSlo" class="btn-primary text-xs h-9 px-4">{{ t('monitor_detail.slo_save') }}</button>
        <button @click="sloEditing = false" class="btn-ghost text-xs h-9 px-3">{{ t('common.cancel') }}</button>
      </div>
    </div>

    <!-- Annotations -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.annotations') }}</h2>
        <button @click="showAnnForm = !showAnnForm"
          class="btn-ghost text-xs flex items-center gap-1">
          <span>+</span> {{ t('monitor_detail.add_annotation') }}
        </button>
      </div>

      <div v-if="showAnnForm" class="flex flex-wrap gap-3 mb-4 p-3 bg-gray-800/40 rounded-lg border border-gray-700">
        <input v-model="newAnnotation.annotated_at" type="datetime-local"
          class="input text-xs flex-shrink-0" />
        <input v-model="newAnnotation.content" class="input text-xs flex-1 min-w-48"
          :placeholder="t('monitor_detail.annotation_content')" @keydown.enter="addAnnotation" />
        <button @click="addAnnotation" class="btn-primary text-xs px-3 h-9">{{ t('monitor_detail.add_annotation') }}</button>
        <button @click="showAnnForm = false" class="btn-ghost text-xs px-3 h-9">{{ t('common.cancel') }}</button>
      </div>

      <div v-if="annotations.length" class="space-y-1.5">
        <div v-for="a in annotations" :key="a.id"
          class="flex items-center gap-3 py-2 px-3 rounded-lg bg-gray-800/30 group">
          <span class="w-0.5 h-5 bg-indigo-500 rounded-full flex-shrink-0" />
          <div class="flex-1 min-w-0">
            <p class="text-sm text-gray-200">{{ a.content }}</p>
            <p class="text-xs text-gray-500 mt-0.5">
              {{ new Date(a.annotated_at).toLocaleString(locale.value) }}
              <span v-if="a.created_by" class="ml-2 text-gray-600">· {{ a.created_by }}</span>
            </p>
          </div>
          <button @click="removeAnnotation(a.id)"
            class="opacity-0 group-hover:opacity-100 text-xs text-red-500 hover:text-red-400 transition-opacity px-1">
            ✕
          </button>
        </div>
      </div>
      <p v-else class="text-gray-600 text-sm text-center py-4">
        No annotations — mark your deployments and interventions here
      </p>
    </div>

    <!-- DNS: resolution history table -->
    <div v-if="monitor.check_type === 'dns'" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">All resolutions</h2>
        <span v-if="monitor.dns_expected_value" class="text-xs text-gray-500 font-mono bg-gray-800 px-2 py-1 rounded">
          expected value: {{ monitor.dns_expected_value }}
        </span>
      </div>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 border-b border-gray-800">
            <th class="pb-2 text-left w-4"></th>
            <th class="pb-2 text-left">Time</th>
            <th class="pb-2 text-left">Probe</th>
            <th class="pb-2 text-left">{{ t('common.status') }}</th>
            <th class="pb-2 text-left">Returned value</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-800">
          <tr v-for="(r, idx) in results.slice(0, 100)" :key="r.id"
            :class="isDnsValueChange(idx) ? 'bg-amber-950/20' : ''"
          >
            <!-- Change indicator -->
            <td class="py-2 pr-1">
              <span v-if="isDnsValueChange(idx)" class="text-amber-400 text-xs" title="Valeur différente du check précédent">⚡</span>
            </td>
            <td class="py-2 text-gray-400 text-xs whitespace-nowrap">{{ formatDate(r.checked_at) }}</td>
            <td class="py-2 text-xs">
              <span class="font-medium" :style="`color:${probeColor(r.probe_id)}`">
                {{ probeName(r.probe_id) }}
              </span>
            </td>
            <td class="py-2">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                :class="{
                  'bg-emerald-900/50 text-emerald-400': r.status === 'up',
                  'bg-red-900/50 text-red-400': r.status === 'down',
                  'bg-amber-900/50 text-amber-400': r.status === 'timeout',
                  'bg-orange-900/50 text-orange-400': r.status === 'error',
                }">
                {{ r.status }}
              </span>
            </td>
            <td class="py-2 text-xs font-mono max-w-xs"
              :title="dnsValueStr(r) || r.error_message || ''">
              <span v-if="dnsValueStr(r)"
                :class="isDnsValueChange(idx) ? 'text-amber-300 font-semibold' : 'text-emerald-400'">
                {{ dnsValueStr(r) }}
              </span>
              <span v-else-if="r.error_message" class="text-red-300 truncate block max-w-xs">{{ r.error_message }}</span>
              <span v-else class="text-gray-600">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Recent checks table (HTTP / TCP / Keyword / JSON — not scenario, not dns) -->
    <div v-if="!['dns', 'scenario'].includes(monitor.check_type)" class="card">
      <h2 class="text-sm font-semibold text-gray-300 mb-4">{{ t('monitor_detail.recent_checks') }}</h2>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 border-b border-gray-800">
            <th class="pb-2 text-left">Time</th>
            <th class="pb-2 text-left">Probe</th>
            <th class="pb-2 text-left">{{ t('common.status') }}</th>
            <th v-if="!noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left">HTTP</th>
            <th class="pb-2 text-left">Réponse</th>
            <th v-if="monitor.check_type === 'http' || monitor.check_type === 'keyword' || monitor.check_type === 'json_path'" class="pb-2 text-left hidden xl:table-cell">Waterfall</th>
            <th v-if="monitor.check_type === 'scenario'" class="pb-2 text-left">Étapes</th>
            <th v-if="!noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left hidden md:table-cell">Redirections</th>
            <th v-if="monitor.ssl_check_enabled" class="pb-2 text-left hidden lg:table-cell">SSL</th>
            <th v-if="noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left hidden md:table-cell">Erreur</th>
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
              <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                :class="{
                  'bg-emerald-900/50 text-emerald-400': r.status === 'up',
                  'bg-red-900/50 text-red-400': r.status === 'down',
                  'bg-amber-900/50 text-amber-400': r.status === 'timeout',
                  'bg-orange-900/50 text-orange-400': r.status === 'error',
                }">
                {{ r.status }}
              </span>
            </td>
            <td v-if="!noHttpTypes.includes(monitor.check_type)" class="py-2 text-gray-300">{{ r.http_status ?? '—' }}</td>
            <td class="py-2 text-gray-300">{{ r.response_time_ms ? Math.round(r.response_time_ms) + 'ms' : '—' }}</td>
            <!-- Waterfall timing mini-bar -->
            <td v-if="monitor.check_type === 'http' || monitor.check_type === 'keyword' || monitor.check_type === 'json_path'" class="py-2 hidden xl:table-cell">
              <div v-if="r.ttfb_ms != null" class="flex items-center gap-1.5 text-xs font-mono min-w-[120px]">
                <div class="flex h-2 rounded overflow-hidden flex-1 bg-gray-800">
                  <div class="bg-blue-500/70 h-full" :style="`width:${Math.round((r.dns_resolve_ms || 0) / r.response_time_ms * 100)}%`" title="DNS"></div>
                  <div class="bg-amber-500/70 h-full" :style="`width:${Math.round(r.ttfb_ms / r.response_time_ms * 100)}%`" title="TTFB"></div>
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
            <td v-if="!noHttpTypes.includes(monitor.check_type)" class="py-2 text-gray-400 hidden md:table-cell">{{ r.redirect_count }}</td>
            <td v-if="monitor.ssl_check_enabled" class="py-2 hidden lg:table-cell">
              <span v-if="r.ssl_valid === null || r.ssl_valid === undefined" class="text-gray-600 text-xs">—</span>
              <span v-else-if="r.ssl_valid" class="text-xs text-emerald-400">✓ {{ r.ssl_days_remaining }}j</span>
              <span v-else class="text-xs text-red-400">✗ expired</span>
            </td>
            <td v-if="noHttpTypes.includes(monitor.check_type)" class="py-2 text-xs text-red-300 hidden md:table-cell truncate max-w-xs">
              {{ r.error_message || '—' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Métriques custom push -->
    <div class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">{{ t('monitor_detail.custom_metrics') }}</h2>
        <button
          @click="showPushUrlModal = true"
          class="btn-secondary text-xs"
        >
          {{ t('monitor_detail.push_url') }}
        </button>
      </div>

      <!-- Charts by metric_name -->
      <div v-if="customMetricNames.length" class="space-y-6">
        <div v-for="mName in customMetricNames" :key="mName">
          <p class="text-xs font-mono text-gray-400 mb-2">{{ mName }}
            <span v-if="customMetricUnit(mName)" class="text-gray-600 ml-1">({{ customMetricUnit(mName) }})</span>
          </p>
          <apexchart
            type="line"
            height="160"
            :options="customMetricOptions(mName)"
            :series="customMetricSeries(mName)"
          />
        </div>
      </div>
      <p v-else class="text-gray-500 text-sm text-center py-6">
        No metrics pushed yet — use the push URL to send business metrics.
      </p>
    </div>

    </div><!-- end Disponibilité tab -->

    <!-- Modal URL de push -->
    <div v-if="showPushUrlModal"
      class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      @click.self="showPushUrlModal = false"
    >
      <div class="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-xl shadow-2xl">
        <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
          <h3 class="text-sm font-semibold text-white">URL de push — Métriques custom</h3>
          <button @click="showPushUrlModal = false" class="text-gray-500 hover:text-white text-lg leading-none px-1">✕</button>
        </div>
        <div class="p-5 space-y-4">
          <div>
            <p class="text-xs text-gray-500 mb-1">Endpoint</p>
            <code class="block text-xs font-mono bg-gray-800 text-blue-300 px-3 py-2 rounded break-all">
              POST {{ apiBase }}/api/v1/metrics/{{ monitor?.id }}
            </code>
          </div>
          <div>
            <p class="text-xs text-gray-500 mb-1">Exemple curl</p>
            <pre class="text-xs font-mono bg-gray-800 text-gray-300 px-3 py-2 rounded overflow-x-auto whitespace-pre">curl -X POST \
  {{ apiBase }}/api/v1/metrics/{{ monitor?.id }} \
  -H "Authorization: Bearer &lt;votre_token_jwt&gt;" \
  -H "Content-Type: application/json" \
  -d '{"metric_name":"orders_per_minute","value":42,"unit":"req/min"}'</pre>
          </div>
          <div class="text-xs text-gray-500">
            <p>Champs disponibles : <code class="text-gray-300">metric_name</code> (requis), <code class="text-gray-300">value</code> (requis), <code class="text-gray-300">unit</code> (optionnel), <code class="text-gray-300">pushed_at</code> (ISO 8601, optionnel).</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Dépendances (section commune, tous onglets) ──────────────────────── -->
    <div class="mt-8 card">
      <MonitorDependencies
        :monitor-id="String(monitor.id)"
        :all-monitors="allMonitors"
      />
    </div>

    <!-- ── Onglet Carte ─────────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_MAP">
      <div ref="probeMapEl" class="rounded-xl overflow-hidden" style="height: 480px;"></div>

      <!-- Sondes sans coordonnées -->
      <div v-if="probesWithoutCoords.length" class="mt-6">
        <h3 class="text-sm font-semibold text-gray-400 mb-3">Unlocated probes</h3>
        <div class="space-y-2">
          <div v-for="p in probesWithoutCoords" :key="p.probe_id"
            class="flex items-center gap-3 text-sm text-gray-300">
            <span class="w-2 h-2 rounded-full" :class="markerColor(p).dot"></span>
            <span class="font-medium">{{ p.name }}</span>
            <span class="text-gray-500">{{ p.location_name }}</span>
            <span class="text-xs" :class="markerColor(p).text">{{ statusLabel(p) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- DNS drift alert suggestion modal -->
    <div v-if="dnsAlertModal" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-sm p-6">
        <h3 class="text-base font-semibold text-white mb-1">Créer une règle d'alerte ?</h3>
        <p class="text-sm text-gray-400 mb-4">
          Le DNS Drift est activé mais aucune règle d'alerte <code class="text-emerald-400">any_down</code> n'existe pour ce moniteur.
          Sans règle, les dérives DNS seront détectées mais aucune notification ne sera envoyée.
        </p>
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-300 mb-1">Canal de notification</label>
          <select v-model="dnsAlertChannelId" class="input w-full">
            <option v-for="ch in dnsAlertChannels" :key="ch.id" :value="ch.id">
              {{ ch.name }} ({{ ch.type }})
            </option>
          </select>
        </div>
        <button @click="createDnsAlertRule" :disabled="dnsAlertCreating || !dnsAlertChannelId" class="w-full btn-primary disabled:opacity-50 mb-3">
          {{ dnsAlertCreating ? 'Création…' : 'Créer la règle d\'alerte' }}
        </button>
        <button @click="toggleDnsSetting('dns_drift_alert'); dnsAlertModal = false" class="w-full text-xs text-gray-500 hover:text-gray-300">
          Désactiver le DNS Drift
        </button>
      </div>
    </div>

    <!-- Screenshot lightbox (global — accessible depuis n'importe quel onglet) -->
    <div v-if="screenshotModal.open"
      class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
      @click.self="screenshotModal.open = false"
    >
      <div class="relative max-w-5xl w-full">
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm text-gray-300">{{ screenshotModal.label }}</span>
          <button @click="screenshotModal.open = false" class="text-gray-400 hover:text-white text-xl leading-none">✕</button>
        </div>
        <img :src="screenshotModal.src" class="w-full rounded-lg border border-gray-700 shadow-2xl" />
      </div>
    </div>
    <EditMonitorModal v-if="editingMonitor" :monitor="editingMonitor" @close="editingMonitor = null" @updated="onMonitorUpdated" />
  </div>
  <div v-else class="p-8 text-gray-400">{{ t('common.loading') }}</div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Shield, ShieldAlert, ShieldCheck } from 'lucide-vue-next'
import api from '../api/client'
import { monitorsApi, triggerCheck, getSlaReport, listAnnotations, createAnnotation, deleteAnnotation, getSlo } from '../api/monitors'
import { probesApi } from '../api/probes'
import { metricsApi } from '../api/metrics'
import { incidentUpdatesApi } from '../api/incidentUpdates'
import MonitorDependencies from '../components/monitors/MonitorDependencies.vue'
import EditMonitorModal from '../components/monitors/EditMonitorModal.vue'
import UptimeHeatmap from '../components/monitors/UptimeHeatmap.vue'

const { t, locale } = useI18n()

const route = useRoute()
const router = useRouter()
const monitor   = ref(null)
const results   = ref([])
const uptime24  = ref(null)
const uptime7d  = ref(null)
const probeMap  = ref({})   // probeId → { name, location_name }
const allMonitors = ref([]) // for dependency picker
const editingMonitor = ref(null)

function onMonitorUpdated() {
  editingMonitor.value = null
  loadAll()
}

async function loadAll() {
  const id    = route.params.id
  const since = new Date(Date.now() - chartWindow.value * 60 * 60 * 1000).toISOString()
  const [monResp, resResp, up24Resp, up7dResp] = await Promise.all([
    monitorsApi.get(id),
    monitorsApi.results(id, { limit: 2000, since }),
    monitorsApi.uptime(id, 24),
    monitorsApi.uptime(id, 168),
  ])
  monitor.value  = monResp.data
  results.value  = resResp.data
  uptime24.value = up24Resp.data
  uptime7d.value = up7dResp.data
}

// ── Incidents & Post-mortem ───────────────────────────────────────────────────
const incidents = ref([])
const incidentError = ref(null)
const expandedIncident = ref(null)
const incidentUpdates = ref([])
const incidentUpdatesLoading = ref(false)
const newUpdate = ref({ status: 'investigating', message: '', is_public: true })

async function toggleIncidentUpdates(incidentId) {
  if (expandedIncident.value === incidentId) {
    expandedIncident.value = null
    return
  }
  expandedIncident.value = incidentId
  incidentUpdatesLoading.value = true
  try {
    const { data } = await incidentUpdatesApi.list(incidentId)
    incidentUpdates.value = data
  } finally {
    incidentUpdatesLoading.value = false
  }
}

async function postIncidentUpdate(incidentId) {
  if (!newUpdate.value.message.trim()) return
  try {
    await incidentUpdatesApi.create(incidentId, { ...newUpdate.value })
    newUpdate.value.message = ''
    const { data } = await incidentUpdatesApi.list(incidentId)
    incidentUpdates.value = data
  } catch {
    // ignore
  }
}

async function deleteIncidentUpdate(incidentId, updateId) {
  try {
    await incidentUpdatesApi.delete(incidentId, updateId)
    incidentUpdates.value = incidentUpdates.value.filter(u => u.id !== updateId)
  } catch {
    // ignore
  }
}

async function loadIncidents() {
  incidentError.value = null
  try {
    const { data } = await monitorsApi.incidents(route.params.id, { limit: 20 })
    incidents.value = data
  } catch {
    incidents.value = []
    incidentError.value = t('common.error')
    setTimeout(() => { incidentError.value = null }, 5000)
  }
}

function downloadIncidentsCsv() {
  if (!incidents.value.length) return
  const headers = ['id', 'started_at', 'resolved_at', 'duration_seconds', 'scope', 'affected_probe_ids', 'dependency_suppressed', 'group_id']
  const rows = incidents.value.map(inc =>
    headers.map(h => {
      const v = inc[h]
      if (v === null || v === undefined) return ''
      if (Array.isArray(v)) return `"${v.join(';')}"`
      return `"${String(v).replace(/"/g, '""')}"`
    }).join(',')
  )
  const csv = [headers.join(','), ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `incidents-${route.params.id}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

const postmortem = ref({ open: false, loading: false, content: '', incidentId: null })

async function openPostmortem(inc) {
  postmortem.value = { open: true, loading: true, content: '', incidentId: inc.id }
  try {
    const { data } = await monitorsApi.getPostmortem(route.params.id, inc.id)
    postmortem.value.content = data.content
  } catch (e) {
    postmortem.value.content = `Erreur lors de la génération du post-mortem : ${e.response?.data?.detail || e.message}`
  } finally {
    postmortem.value.loading = false
  }
}

function downloadPostmortem() {
  if (!postmortem.value.content) return
  const blob = new Blob([postmortem.value.content], { type: 'text/markdown;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `postmortem-${monitor.value?.name || 'monitor'}-${postmortem.value.incidentId?.slice(0, 8)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

// ── SLO / Error Budget ────────────────────────────────────────────────────────
const sloData     = ref(null)
const sloEditing  = ref(false)
const sloEditTarget = ref(null)
const sloEditDays   = ref(30)

async function loadSlo() {
  if (!monitor.value || monitor.value.slo_target == null) return
  try {
    sloData.value = await getSlo(monitor.value.id)
  } catch {
    sloData.value = null
  }
}

async function saveSlo() {
  await monitorsApi.update(monitor.value.id, {
    slo_target: sloEditTarget.value,
    slo_window_days: sloEditDays.value,
  })
  monitor.value.slo_target = sloEditTarget.value
  monitor.value.slo_window_days = sloEditDays.value
  sloEditing.value = false
  if (sloEditTarget.value != null) await loadSlo()
}

// ── SLA Report ────────────────────────────────────────────────────────────────
const slaFrom    = ref('')
const slaTo      = ref('')
const slaLoading = ref(false)
const slaResult  = ref(null)

async function downloadSlaReport() {
  if (!slaFrom.value) return
  slaLoading.value = true
  try {
    const from = new Date(slaFrom.value).toISOString()
    const to   = slaTo.value ? new Date(slaTo.value + 'T23:59:59').toISOString() : undefined
    slaResult.value = await getSlaReport(monitor.value.id, from, to)
    const blob = new Blob([JSON.stringify(slaResult.value, null, 2)], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `sla-${monitor.value.name}-${slaFrom.value}.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('SLA report error', e)
  } finally {
    slaLoading.value = false
  }
}

// ── Annotations ───────────────────────────────────────────────────────────────
const annotations   = ref([])
const showAnnForm   = ref(false)
const newAnnotation = ref({ content: '', annotated_at: '' })

async function loadAnnotations() {
  try { annotations.value = await listAnnotations(route.params.id) }
  catch { annotations.value = [] }
}

async function addAnnotation() {
  if (!newAnnotation.value.content || !newAnnotation.value.annotated_at) return
  await createAnnotation(route.params.id, {
    content: newAnnotation.value.content,
    annotated_at: new Date(newAnnotation.value.annotated_at).toISOString(),
  })
  newAnnotation.value = { content: '', annotated_at: '' }
  showAnnForm.value = false
  await loadAnnotations()
}

async function removeAnnotation(id) {
  await deleteAnnotation(route.params.id, id)
  await loadAnnotations()
}

// ── "Tester maintenant" ───────────────────────────────────────────────────────
const testing      = ref(false)
const testingState = ref(null)  // null | 'queued' | 'running' | 'done'
const newResultId  = ref(null)
let   testPollInterval   = null
let   testPollTimeout    = null  // 30-second hard limit
let   highlightTimeout   = null  // 5-second highlight clear
const testingElapsed = ref(0)
let   elapsedInterval = null

async function loadResults() {
  const id    = route.params.id
  const since = new Date(Date.now() - chartWindow.value * 60 * 60 * 1000).toISOString()
  const { data } = await monitorsApi.results(id, { limit: 2000, since })
  // Only update ref when data actually changed to avoid spurious re-renders
  const latest = data[0]
  const current = results.value[0]
  if (!current || !latest || latest.id !== current.id || data.length !== results.value.length) {
    results.value = data
  }
}

async function handleTriggerCheck() {
  if (testing.value) return
  testing.value      = true
  testingState.value = 'queued'
  newResultId.value  = null
  testingElapsed.value = 0
  elapsedInterval = setInterval(() => { testingElapsed.value++ }, 1000)

  const clickedAt = new Date().toISOString()

  try {
    await triggerCheck(monitor.value.id)
    testingState.value = 'running'
  } catch {
    clearInterval(elapsedInterval)
    elapsedInterval = null
    testingElapsed.value = 0
    testing.value      = false
    testingState.value = null
    return
  }

  // Poll every 3 s; hard-cancel after 30 s
  const stopPolling = () => {
    clearInterval(testPollInterval)
    clearTimeout(testPollTimeout)
    clearInterval(elapsedInterval)
    testPollInterval = null
    testPollTimeout  = null
    elapsedInterval  = null
  }

  testPollTimeout = setTimeout(() => {
    stopPolling()
    testing.value      = false
    testingState.value = null
  }, 30000)

  testPollInterval = setInterval(async () => {
    try {
      await loadResults()
      const fresh = results.value.find(r => r.checked_at > clickedAt)
      if (fresh) {
        stopPolling()
        newResultId.value  = fresh.id
        testingState.value = 'done'
        testing.value      = false
        // Remove highlight after 5 s; track timeout for unmount cleanup
        highlightTimeout = setTimeout(() => { newResultId.value = null }, 5000)
      }
    } catch { /* network error — keep polling */ }
  }, 3000)
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
const TAB_AVAILABILITY = 'availability'
const TAB_SCENARIO = 'scenario'
const TAB_MAP = 'map'

const tabLabel = (tab) => ({
  [TAB_AVAILABILITY]: t('monitor_detail.tab_availability'),
  [TAB_SCENARIO]: t('monitor_detail.tab_scenario'),
  [TAB_MAP]: t('monitor_detail.tab_map'),
}[tab] ?? tab)

const viewTabs = computed(() => {
  const tabs = [TAB_AVAILABILITY]
  if (monitor.value?.check_type === 'scenario') tabs.push(TAB_SCENARIO)
  tabs.push(TAB_MAP)
  return tabs
})
const activeTab = ref(TAB_AVAILABILITY)

// Auto-switch to Scénario tab when monitor loads and is scenario type
watch(monitor, (m) => {
  if (m?.check_type === 'scenario' && activeTab.value === TAB_AVAILABILITY) {
    activeTab.value = TAB_SCENARIO
  }
}, { once: true })

// ── Scenario run selection ────────────────────────────────────────────────────
const selectedRunId = ref(null)

// ── Map (Carte tab) ───────────────────────────────────────────────────────────
const probeMapEl = ref(null)
const probeStatuses = ref([])  // list of ProbeMonitorStatus
let monitorLeafletMap = null
let monitorMarkers = []

const probesWithCoords = computed(() =>
  probeStatuses.value.filter(p => p.latitude != null && p.longitude != null)
)
const probesWithoutCoords = computed(() =>
  probeStatuses.value.filter(p => p.latitude == null || p.longitude == null)
)

function markerColor(p) {
  if (!p.last_status) return { dot: 'bg-gray-500', text: 'text-gray-500', hex: '#6b7280' }
  if (p.last_status === 'up') return { dot: 'bg-emerald-400', text: 'text-emerald-400', hex: '#34d399' }
  return { dot: 'bg-red-500', text: 'text-red-400', hex: '#ef4444' }
}

function statusLabel(p) {
  if (!p.last_status) return t('monitor_detail.no_check_yet')
  return p.last_status + (p.response_time_ms ? ` — ${Math.round(p.response_time_ms)}ms` : '')
}

async function initMonitorMap() {
  if (!probeMapEl.value) return
  const L = (await import('leaflet')).default
  await import('leaflet/dist/leaflet.css')

  delete L.Icon.Default.prototype._getIconUrl
  L.Icon.Default.mergeOptions({
    iconRetinaUrl: new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href,
    iconUrl: new URL('leaflet/dist/images/marker-icon.png', import.meta.url).href,
    shadowUrl: new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href,
  })

  monitorLeafletMap = L.map(probeMapEl.value).setView([20, 0], 2)
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
  }).addTo(monitorLeafletMap)

  monitorMarkers.forEach(m => m.remove())
  monitorMarkers = []

  for (const p of probesWithCoords.value) {
    const col = markerColor(p)
    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:14px;height:14px;border-radius:50%;
        background:${col.hex};
        border:2px solid ${col.hex}aa;
        box-shadow:0 0 6px ${col.hex}88;
      "></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    })
    const checkedAt = p.last_checked_at
      ? new Date(p.last_checked_at).toLocaleString(locale.value) : 'Never'
    const marker = L.marker([p.latitude, p.longitude], { icon })
      .addTo(monitorLeafletMap)
      .bindPopup(`
        <b>${p.name}</b><br>
        ${p.location_name}<br>
        <span style="color:${col.hex}">● ${p.last_status ?? t('monitor_detail.no_check_yet')}</span>
        ${p.response_time_ms != null ? ` — ${Math.round(p.response_time_ms)}ms` : ''}<br>
        <small>${checkedAt}</small>
      `)
    monitorMarkers.push(marker)
  }
}

async function setTab(tab) {
  activeTab.value = tab
  if (tab === TAB_MAP) {
    if (!probeStatuses.value.length) {
      try {
        const { data } = await monitorsApi.probeStatus(route.params.id)
        probeStatuses.value = data
      } catch {}
    }
    await nextTick()
    if (!monitorLeafletMap) await initMonitorMap()
  }
}

const probeColors = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#06b6d4']

// ── helpers ──────────────────────────────────────────────────────────────────
const statusMap  = { up: 'bg-emerald-400', down: 'bg-red-500', timeout: 'bg-amber-400', error: 'bg-orange-500' }
const statusClass = computed(() => statusMap[monitor.value?._lastStatus ?? monitor.value?.last_status] || 'bg-gray-600')

const latestSsl = computed(() =>
  results.value.find(r => r.ssl_valid !== null && r.ssl_valid !== undefined) ?? null
)

const latestDomainExpiry = computed(() =>
  results.value.find(r => r.ssl_expires_at !== null && r.ssl_expires_at !== undefined) ?? null
)

const latestScenarioResult = computed(() =>
  results.value.find(r => r.scenario_result != null)?.scenario_result ?? null
)

// ── Tendance temps de réponse ─────────────────────────────────────────────────
const responseTrend = computed(() => {
  if (!results.value.length) return null
  const now = Date.now()
  const h6  = 6 * 3600 * 1000
  const recent = results.value.filter(r =>
    r.response_time_ms != null && new Date(r.checked_at).getTime() > now - h6
  )
  const older = results.value.filter(r =>
    r.response_time_ms != null &&
    new Date(r.checked_at).getTime() <= now - h6 &&
    new Date(r.checked_at).getTime() > now - 2 * h6
  )
  if (recent.length < 3 || older.length < 3) return null
  const avgRecent = recent.reduce((s, r) => s + r.response_time_ms, 0) / recent.length
  const avgOlder  = older.reduce((s,  r) => s + r.response_time_ms, 0) / older.length
  const pct = ((avgRecent - avgOlder) / avgOlder) * 100
  if (Math.abs(pct) < 10) return null
  return { up: pct > 0, pct: Math.abs(pct).toFixed(0) }
})

// ── DNS changelog ─────────────────────────────────────────────────────────────
// Normalize DNS values: sort for stable comparison — ["5.6.7.8","1.2.3.4"] === ["1.2.3.4","5.6.7.8"]
function normalizeDnsValue(vals) {
  if (!vals || !vals.length) return null
  return [...vals].sort().join(', ')
}

function dnsValueStr(r) {
  if (r.status !== 'up') return null
  if (r.dns_resolved_values?.length) return r.dns_resolved_values.join(', ')
  return null
}

// results are DESC (newest first) — compare chronologically (reversed)
const dnsChangelog = computed(() => {
  if (monitor.value?.check_type !== 'dns') return []
  const chronological = [...results.value].reverse()
  const changes = []
  let lastNorm = undefined // undefined = no previous result yet
  let lastVals = null
  for (const r of chronological) {
    const vals = r.status === 'up' ? (r.dns_resolved_values ?? []) : null
    const norm = normalizeDnsValue(vals)
    if (norm !== lastNorm) {
      changes.push({
        checked_at: r.checked_at,
        probe_id: r.probe_id,
        old_value: lastNorm === undefined ? null : (lastVals ? lastVals.join(', ') : null),
        new_value: vals ? vals.join(', ') : null,
      })
      lastNorm = norm
      lastVals = vals
    }
  }
  return changes.reverse() // most recent first
})

// Returns true if the result at `idx` has a genuinely different value set than the next one
function isDnsValueChange(idx) {
  const slice = results.value.slice(0, 100)
  if (idx >= slice.length - 1) return false
  const curr = normalizeDnsValue(slice[idx].status === 'up' ? slice[idx].dns_resolved_values : null)
  const prev = normalizeDnsValue(slice[idx + 1].status === 'up' ? slice[idx + 1].dns_resolved_values : null)
  return curr !== prev
}

// Most recent successful DNS resolution
const currentDnsValues = computed(() => {
  const r = results.value.find(r => r.status === 'up' && r.dns_resolved_values?.length)
  return r?.dns_resolved_values ?? null
})

// Auto-select the most recent run when results load
watch(results, (res) => {
  if (monitor.value?.check_type === 'scenario' && res.length && !selectedRunId.value) {
    selectedRunId.value = res[0].id
  }
}, { immediate: true })

const screenshotModal = ref({ open: false, src: '', label: '' })

function openScreenshot(src, label) {
  screenshotModal.value = { open: true, src, label }
}

const STEP_TYPE_COLORS = {
  navigate:       'bg-blue-900/60 text-blue-300',
  click:          'bg-violet-900/60 text-violet-300',
  fill:           'bg-cyan-900/60 text-cyan-300',
  select:         'bg-cyan-900/60 text-cyan-300',
  hover:          'bg-violet-900/60 text-violet-300',
  scroll:         'bg-gray-800 text-gray-400',
  wait_element:   'bg-amber-900/60 text-amber-300',
  wait_time:      'bg-amber-900/60 text-amber-300',
  assert_text:    'bg-emerald-900/60 text-emerald-300',
  assert_visible: 'bg-emerald-900/60 text-emerald-300',
  assert_url:     'bg-emerald-900/60 text-emerald-300',
  screenshot:     'bg-pink-900/60 text-pink-300',
  group:          'bg-gray-700 text-gray-400',
  extract:        'bg-purple-900/60 text-purple-300',
}

function stepTypeBadgeClass(type) {
  return STEP_TYPE_COLORS[type] ?? 'bg-gray-800 text-gray-400'
}

// Map probe_id → ordered index (stable colors across renders)
const probeIndexMap = computed(() => {
  const ids = [...new Set(results.value.map(r => r.probe_id))]
  return Object.fromEntries(ids.map((id, i) => [id, i]))
})

function probeName(probeId) {
  const p = probeMap.value[probeId]
  return p ? p.location_name : probeId.slice(0, 8) + '…'
}

function probeColor(probeId) {
  const idx = probeIndexMap.value[probeId] ?? 0
  return probeColors[idx % probeColors.length]
}

// ── Chart window & alert threshold ────────────────────────────────────────────
const CHART_WINDOWS = [
  { h: 6,   label: '6h' },
  { h: 24,  label: '24h' },
  { h: 72,  label: '3d' },
  { h: 168, label: '7d' },
]
const chartWindow = ref(24)

// Reload results when chart window changes (watch must be after chartWindow declaration)
watch(chartWindow, loadResults)

function chartBucketMin(h) {
  if (h <= 6)  return 15
  if (h <= 24) return 30
  if (h <= 72) return 120
  return 240
}

const alertRules = ref([])
const alertRulesLoaded = ref(false)

async function loadAlertRules() {
  if (!monitor.value) return
  try {
    const { data } = await api.get('/alerts/rules')
    alertRules.value = data.filter(r => r.monitor_id && String(r.monitor_id) === String(monitor.value.id))
  } catch {}
  alertRulesLoaded.value = true
}

// ── Auto-alert setup modal (A2 banner) ───────────────────────────────────────
const showAutoAlertModal = ref(false)
const autoAlertChannels = ref([])
const autoAlertSelectedChannels = ref([])
const autoAlertCreating = ref(false)

watch(showAutoAlertModal, async (v) => {
  if (!v) return
  try {
    const { data } = await api.get('/alerts/channels')
    autoAlertChannels.value = data
    autoAlertSelectedChannels.value = data.map(c => c.id)
  } catch {}
})

async function createAutoAlertRules() {
  if (!monitor.value || autoAlertSelectedChannels.value.length === 0) return
  autoAlertCreating.value = true
  try {
    await api.post(`/alerts/auto-rules/${monitor.value.id}`, null, {
      params: { channel_ids: autoAlertSelectedChannels.value },
    })
    showAutoAlertModal.value = false
    await loadAlertRules()
  } catch {}
  autoAlertCreating.value = false
}

const rtThresholdMs = computed(() => {
  const rule = alertRules.value.find(r => r.condition === 'response_time_above' && r.threshold_value != null)
  return rule?.threshold_value ?? null
})

// ── Custom metrics push ───────────────────────────────────────────────────────
const customMetrics = ref([])
const showPushUrlModal = ref(false)
const apiBase = window.location.origin

async function loadCustomMetrics() {
  if (!monitor.value) return
  try {
    const { data } = await metricsApi.list(monitor.value.id, { hours: 24 })
    customMetrics.value = data
  } catch {
    customMetrics.value = []
  }
}

const customMetricNames = computed(() => {
  return [...new Set(customMetrics.value.map(m => m.metric_name))]
})

function customMetricUnit(name) {
  return customMetrics.value.find(m => m.metric_name === name)?.unit ?? null
}

function customMetricSeries(name) {
  const pts = customMetrics.value
    .filter(m => m.metric_name === name)
    .map(m => ({ x: new Date(m.pushed_at).getTime(), y: m.value }))
    .sort((a, b) => a.x - b.x)
  return [{ name, data: pts }]
}

function customMetricOptions(name) {
  const unit = customMetricUnit(name)
  return {
    chart: { type: 'line', toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
    dataLabels: { enabled: false },
    stroke: { curve: 'smooth', width: 2 },
    xaxis: { type: 'datetime', labels: { style: { colors: '#6b7280' }, datetimeUTC: false } },
    yaxis: { labels: { style: { colors: '#6b7280' }, formatter: v => unit ? `${v} ${unit}` : String(v) } },
    grid: { borderColor: '#1e293b' },
    theme: { mode: 'dark' },
    tooltip: { x: { format: 'dd/MM HH:mm:ss' }, y: { formatter: v => unit ? `${v} ${unit}` : String(v) } },
    legend: { show: false },
  }
}

// ── Chart: response time per probe (line) ────────────────────────────────────
const rtSeries = computed(() => {
  if (!results.value.length) return []
  const byProbe = {}
  for (const r of results.value) {
    if (r.response_time_ms === null) continue
    if (!byProbe[r.probe_id]) byProbe[r.probe_id] = []
    byProbe[r.probe_id].push({ x: new Date(r.checked_at).getTime(), y: Math.round(r.response_time_ms) })
  }
  return Object.entries(byProbe).map(([pid, data], i) => ({
    name: probeName(pid),
    data: data.sort((a, b) => a.x - b.x),
    color: probeColors[i % probeColors.length],
  }))
})

const rtOptions = computed(() => ({
  chart: { type: 'line', toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth', width: 2 },
  xaxis: { type: 'datetime', labels: { style: { colors: '#6b7280' }, datetimeUTC: false } },
  yaxis: { labels: { style: { colors: '#6b7280' }, formatter: v => v + 'ms' } },
  legend: { show: false },
  grid: { borderColor: '#1e293b' },
  theme: { mode: 'dark' },
  tooltip: { x: { format: 'dd/MM HH:mm:ss' }, y: { formatter: v => v + ' ms' } },
  annotations: {
    xaxis: annotations.value.map(a => ({
      x: new Date(a.annotated_at).getTime(),
      strokeDashArray: 4,
      borderColor: '#818cf8',
      label: {
        text: a.content.length > 25 ? a.content.slice(0, 25) + '…' : a.content,
        style: { color: '#fff', background: '#4f46e5', fontSize: '10px', padding: { left: 6, right: 6, top: 2, bottom: 2 } },
        position: 'top',
        orientation: 'vertical',
      },
    })),
    yaxis: rtThresholdMs.value != null ? [{
      y: rtThresholdMs.value,
      borderColor: '#f87171',
      strokeDashArray: 4,
      label: {
        text: `Alert: ${rtThresholdMs.value}ms`,
        style: { color: '#fff', background: '#ef4444', fontSize: '10px', padding: { left: 6, right: 6, top: 2, bottom: 2 } },
        position: 'right',
      },
    }] : [],
  },
}))

// ── Chart: aggregated availability (bar, dynamic window) ─────────────────────
const availSeries = computed(() => {
  if (!results.value.length) return [{ name: 'Availability', data: [] }]

  const now    = Date.now()
  const window = chartWindow.value * 60 * 60 * 1000
  const bucket = chartBucketMin(chartWindow.value) * 60 * 1000
  const count  = Math.floor(window / bucket)

  const buckets = Array.from({ length: count }, (_, i) => ({
    ts:    now - window + (i + 1) * bucket,
    total: 0,
    up:    0,
  }))

  for (const r of results.value) {
    const ts  = new Date(r.checked_at).getTime()
    const idx = Math.floor((ts - (now - window)) / bucket)
    if (idx >= 0 && idx < count) {
      buckets[idx].total++
      if (r.status === 'up') buckets[idx].up++
    }
  }

  return [{
    name: 'Availability',
    data: buckets.map(b => ({
      x: b.ts,
      y: b.total > 0 ? Math.round(b.up / b.total * 100) : null,
    })),
  }]
})

const availOptions = computed(() => ({
  chart: { type: 'bar', toolbar: { show: false }, background: 'transparent', animations: { enabled: false } },
  plotOptions: {
    bar: {
      columnWidth: '90%',
      colors: {
        ranges: [
          { from: 0,    to: 49,   color: '#ef4444' },
          { from: 50,   to: 99,   color: '#f59e0b' },
          { from: 99,   to: 100,  color: '#10b981' },
        ],
      },
    },
  },
  dataLabels: { enabled: false },
  xaxis: {
    type: 'datetime',
    labels: { style: { colors: '#6b7280' }, datetimeUTC: false, format: 'HH:mm' },
  },
  yaxis: {
    min: 0, max: 100,
    tickAmount: 4,
    labels: { style: { colors: '#6b7280' }, formatter: v => v + '%' },
  },
  grid: { borderColor: '#1e293b' },
  theme: { mode: 'dark' },
  tooltip: {
    x: { format: 'dd/MM HH:mm' },
    y: { formatter: v => v !== null ? v + '% probes UP' : t('monitor_detail.no_data') },
  },
}))

// ── Helpers ───────────────────────────────────────────────────────────────────
const noHttpTypes = ['tcp', 'udp', 'smtp', 'ping', 'domain_expiry', 'heartbeat', 'composite']

function formatTarget(m) {
  const raw = m.url?.replace(/^https?:\/\//, '') || ''
  if (m.check_type === 'tcp') return m.tcp_port ? `${raw}:${m.tcp_port}` : raw
  if (m.check_type === 'udp') return m.udp_port ? `${raw}:${m.udp_port}` : raw
  if (m.check_type === 'smtp') return m.smtp_port ? `${raw}:${m.smtp_port}` : raw
  if (m.check_type === 'scenario') {
    const firstNav = m.scenario_steps?.find(s => s.type === 'navigate')
    return firstNav?.params?.url?.replace(/^https?:\/\//, '') || 'scenario'
  }
  if (m.check_type === 'composite') return 'composite'
  if (m.check_type === 'heartbeat') return m.heartbeat_slug || 'heartbeat'
  return raw
}

function formatDate(dt) {
  return new Date(dt).toLocaleString(locale.value, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    day: '2-digit', month: '2-digit',
  })
}

function formatDateShort(dt) {
  return new Date(dt).toLocaleDateString(locale.value, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

// ── DNS Baseline ──────────────────────────────────────────────────────────────
const dnsBaselineLoading = ref(false)
const dnsBaselineMsg = ref('')

async function acceptDnsBaseline() {
  dnsBaselineLoading.value = true
  dnsBaselineMsg.value = ''
  try {
    const { data } = await monitorsApi.acceptDnsBaseline(monitor.value.id)
    monitor.value.dns_baseline_ips = data.baseline
    dnsBaselineMsg.value = `Baseline updated: ${data.baseline.join(', ')}`
    setTimeout(() => { dnsBaselineMsg.value = '' }, 4000)
  } catch (e) {
    dnsBaselineMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    dnsBaselineLoading.value = false
  }
}

async function resetDnsBaseline(type = 'all') {
  dnsBaselineLoading.value = true
  dnsBaselineMsg.value = ''
  try {
    await monitorsApi.resetDnsBaseline(monitor.value.id, type)
    if (type === 'internal') {
      monitor.value.dns_baseline_ips_internal = null
    } else if (type === 'external') {
      monitor.value.dns_baseline_ips_external = null
    } else {
      monitor.value.dns_baseline_ips = null
      monitor.value.dns_baseline_ips_internal = null
      monitor.value.dns_baseline_ips_external = null
    }
    dnsBaselineMsg.value = 'Baseline cleared — will re-learn on next check.'
    setTimeout(() => { dnsBaselineMsg.value = '' }, 4000)
  } catch (e) {
    dnsBaselineMsg.value = e.response?.data?.detail || 'Error'
  } finally {
    dnsBaselineLoading.value = false
  }
}

// ── Schema Drift Baseline ─────────────────────────────────────────────────────
async function toggleSchemaDrift(enabled) {
  try {
    await monitorsApi.update(monitor.value.id, { schema_drift_enabled: enabled })
    monitor.value.schema_drift_enabled = enabled
  } catch {
    // ignore
  }
}

async function acceptSchemaBaseline() {
  try {
    const { data } = await monitorsApi.acceptSchemaBaseline(monitor.value.id)
    monitor.value.schema_baseline = data.baseline
    monitor.value.schema_baseline_updated_at = new Date().toISOString()
  } catch (e) {
    alert(e.response?.data?.detail || 'Error accepting baseline')
  }
}

async function resetSchemaBaseline() {
  try {
    await monitorsApi.resetSchemaBaseline(monitor.value.id)
    monitor.value.schema_baseline = null
    monitor.value.schema_baseline_updated_at = null
  } catch {
    // ignore
  }
}

// ── DNS alert suggestion modal ─────────────────────────────────────────────
const dnsAlertModal = ref(false)
const dnsAlertChannels = ref([])
const dnsAlertChannelId = ref('')
const dnsAlertCreating = ref(false)

async function toggleDnsSetting(field) {
  const newVal = !monitor.value[field]
  monitor.value[field] = newVal
  try {
    await monitorsApi.update(monitor.value.id, { [field]: newVal })
  } catch (e) {
    monitor.value[field] = !newVal
    return
  }
  // When enabling dns_drift_alert or dns_split_enabled, check if an any_down rule already exists
  if ((field === 'dns_drift_alert' || field === 'dns_split_enabled') && newVal && monitor.value.dns_drift_alert) {
    try {
      const [chResp, rulesResp] = await Promise.all([
        api.get('/alerts/channels'),
        api.get('/alerts/rules'),
      ])
      const channels = chResp.data
      const hasRule = rulesResp.data.some(r =>
        r.monitor_id === monitor.value.id && r.condition === 'any_down'
      )
      if (!hasRule && channels.length) {
        dnsAlertChannels.value = channels
        dnsAlertChannelId.value = channels[0].id
        dnsAlertModal.value = true
      }
    } catch {}
  }
}

// ── Network scope ────────────────────────────────────────────────────────────
const networkScopeOptions = [
  { value: 'all', icon: '🌍', label: t('monitors.network_scope.all'), desc: t('monitors.network_scope.all_desc') },
  { value: 'internal', icon: '🏠', label: t('monitors.network_scope.internal'), desc: t('monitors.network_scope.internal_desc') },
  { value: 'external', icon: '☁️', label: t('monitors.network_scope.external'), desc: t('monitors.network_scope.external_desc') },
]

async function setNetworkScope(scope) {
  if (monitor.value.network_scope === scope) return
  const prev = monitor.value.network_scope
  monitor.value.network_scope = scope
  try {
    await monitorsApi.update(monitor.value.id, { network_scope: scope })
  } catch {
    monitor.value.network_scope = prev
  }
}

async function createDnsAlertRule() {
  if (!dnsAlertChannelId.value) return
  dnsAlertCreating.value = true
  try {
    await api.post('/alerts/rules', {
      monitor_id: monitor.value.id,
      condition: 'any_down',
      min_duration_seconds: 0,
      channel_ids: [dnsAlertChannelId.value],
    })
    dnsAlertModal.value = false
  } catch (e) {
    alert(e.response?.data?.detail || 'Erreur lors de la création de la règle')
  } finally {
    dnsAlertCreating.value = false
  }
}

// ── Composite members ─────────────────────────────────────────────────────────
const compositeMembers = ref([])
const newMember = ref({ monitor_id: '', role: '', weight: 1 })

function memberName(monitorId) {
  const m = allMonitors.value.find(m => m.id === monitorId)
  return m ? m.name : monitorId.slice(0, 8)
}

const availableMonitors = computed(() =>
  allMonitors.value.filter(m =>
    m.id !== monitor.value?.id &&
    m.check_type !== 'composite' &&
    !compositeMembers.value.some(cm => cm.monitor_id === m.id)
  )
)

async function loadCompositeMembers() {
  if (monitor.value?.check_type !== 'composite') return
  try {
    const { data } = await monitorsApi.listCompositeMembers(monitor.value.id)
    compositeMembers.value = data
  } catch {}
}

async function addCompositeMember() {
  if (!newMember.value.monitor_id) return
  try {
    const { data } = await monitorsApi.addCompositeMember(monitor.value.id, {
      monitor_id: newMember.value.monitor_id,
      role: newMember.value.role || null,
      weight: newMember.value.weight || 1,
    })
    compositeMembers.value.push(data)
    newMember.value = { monitor_id: '', role: '', weight: 1 }
  } catch (e) {
    alert(e.response?.data?.detail || 'Error adding member')
  }
}

async function removeCompositeMember(memberId) {
  try {
    await monitorsApi.removeCompositeMember(monitor.value.id, memberId)
    compositeMembers.value = compositeMembers.value.filter(m => m.id !== memberId)
  } catch (e) {
    alert(e.response?.data?.detail || 'Error removing member')
  }
}

// ── Cleanup ───────────────────────────────────────────────────────────────────
onUnmounted(() => {
  clearInterval(testPollInterval)
  clearTimeout(testPollTimeout)
  clearTimeout(highlightTimeout)
  clearInterval(elapsedInterval)
  testPollInterval = null
  testPollTimeout  = null
  highlightTimeout = null
  elapsedInterval  = null
  if (monitorLeafletMap) {
    monitorLeafletMap.remove()
    monitorLeafletMap = null
  }
})

// ── Mount ─────────────────────────────────────────────────────────────────────
onMounted(async () => {
  const id   = route.params.id
  const since = new Date(Date.now() - chartWindow.value * 60 * 60 * 1000).toISOString()

  const [monResp, resResp, up24Resp, up7dResp] = await Promise.all([
    monitorsApi.get(id),
    monitorsApi.results(id, { limit: 2000, since }),
    monitorsApi.uptime(id, 24),
    monitorsApi.uptime(id, 168),
  ])
  monitor.value  = monResp.data
  results.value  = resResp.data
  uptime24.value = up24Resp.data
  uptime7d.value = up7dResp.data

  // Initialise SLO edit refs from loaded monitor
  sloEditTarget.value = monitor.value.slo_target ?? null
  sloEditDays.value   = monitor.value.slo_window_days ?? 30

  // Load annotations, incidents, SLO, custom metrics, composite members & alert rules non-blocking
  loadAnnotations()
  loadIncidents()
  loadSlo()
  loadCustomMetrics()
  loadCompositeMembers()
  loadAlertRules()

  // Load all monitors for dependency picker
  try {
    const { data } = await monitorsApi.list()
    allMonitors.value = data
  } catch {}

  // Fetch probe names (graceful fallback if not superadmin)
  try {
    const { data } = await probesApi.list()
    probeMap.value = Object.fromEntries(data.map(p => [p.id, p]))
  } catch {}
})
</script>

<style scoped>
.breadcrumb { display: flex; align-items: center; gap: 6px; font-size: 0.8125rem; margin-bottom: 1.25rem; }
.breadcrumb__link { color: var(--text-3); transition: color .15s; }
.breadcrumb__link:hover { color: var(--text-1); }
.breadcrumb__sep { color: var(--text-3); }
.breadcrumb__current { color: var(--text-1); font-weight: 500; }
</style>
