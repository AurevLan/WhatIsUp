<template>
  <div class="page-body" v-if="monitor">
    <!-- Header -->
    <div class="flex items-center gap-4 mb-8">
      <nav class="breadcrumbs">
        <router-link to="/monitors">{{ t('monitors.title') }}</router-link>
        <span class="breadcrumbs__sep">/</span>
        <span class="breadcrumbs__current">{{ monitor.name }}</span>
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
        <div class="mt-2">
          <TagChips :model-value="monitor.tags || []" @update:model-value="onTagsChange" />
        </div>
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
    <MonitorScenarioTab
      v-if="activeTab === TAB_SCENARIO"
      :uptime24="uptime24"
      :uptime7d="uptime7d"
      :results="results"
      v-model:selected-run-id="selectedRunId"
      :new-result-id="newResultId"
      :testing="testing"
      :testing-state="testingState"
      :testing-elapsed="testingElapsed"
      :format-date="formatDate"
      :probe-color="probeColor"
      :probe-name="probeName"
      :step-type-badge-class="stepTypeBadgeClass"
      @trigger-check="handleTriggerCheck"
      @duplicate="duplicateMonitor"
      @schedule-maintenance="openScheduleMaintenance"
      @edit-monitor="editingMonitor = monitor"
      @open-screenshot="e => openScreenshot(e.src, e.label)"
    />

    <!-- ── Disponibilité + Temps de réponse + Checks ─────────────────────── -->
    <div v-if="activeTab === TAB_AVAILABILITY">

    <!-- Stats cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <div class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_24h') }}</p>
        <p class="text-2xl font-bold mt-1" :class="uptime24?.uptime_percent >= 99 ? 'text-emerald-400' : 'text-red-400'">
          {{ uptime24?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
        <UptimeViewSplit :stats="uptime24" />
      </div>
      <div class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.uptime_7d') }}</p>
        <p class="text-2xl font-bold mt-1 text-blue-400">
          {{ uptime7d?.uptime_percent?.toFixed(3) ?? '—' }}%
        </p>
        <UptimeViewSplit :stats="uptime7d" />
      </div>
      <div v-if="isDns" class="card text-center">
        <p class="text-xs text-gray-500">Changes detected</p>
        <p class="text-2xl font-bold mt-1" :class="dnsChangelog.length > 0 ? 'text-amber-400' : 'text-emerald-400'">
          {{ dnsChangelog.length }}
        </p>
      </div>
      <div v-else-if="hasResponseTime" class="card text-center">
        <p class="text-xs text-gray-500">{{ isNetwork ? 'Avg. latency' : 'Avg. response' }}</p>
        <p class="text-2xl font-bold mt-1 text-gray-300">
          {{ uptime24?.avg_response_time_ms ? Math.round(uptime24.avg_response_time_ms) + 'ms' : '—' }}
        </p>
      </div>
      <div v-if="isDns" class="card text-center">
        <p class="text-xs text-gray-500">Last change</p>
        <p class="text-sm font-bold mt-1 text-gray-300">
          {{ dnsChangelog[0] ? formatDateShort(dnsChangelog[0].checked_at) : '—' }}
        </p>
      </div>
      <div v-else-if="hasResponseTime" class="card text-center">
        <p class="text-xs text-gray-500">p95 response</p>
        <p class="text-2xl font-bold mt-1 text-gray-300">
          {{ uptime24?.p95_response_time_ms ? Math.round(uptime24.p95_response_time_ms) + 'ms' : '—' }}
        </p>
      </div>
      <div v-if="responseTrend && hasResponseTime" class="card text-center">
        <p class="text-xs text-gray-500">{{ t('monitor_detail.response_time_trend') }}</p>
        <p class="text-2xl font-bold mt-1" :class="responseTrend.up ? 'text-red-400' : 'text-emerald-400'">
          {{ responseTrend.up ? '↑' : '↓' }} {{ responseTrend.pct }}%
        </p>
        <p class="text-xs text-gray-600 mt-0.5">vs prev. 6h</p>
      </div>
    </div>

    <!-- DNS: current resolved value banner -->
    <div v-if="isDns" class="card mb-6 flex flex-wrap items-center gap-4">
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
    <div v-if="isDns" class="card mb-6">
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
    <div v-if="isDns" class="card mb-6">
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
    <div v-if="hasNetworkScope" class="card mb-6">
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
    <div v-if="isHttpLike && monitor.schema_drift_enabled" class="card mb-6">
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
                Updated {{ fmtDateTime(monitor.schema_baseline_updated_at) }}
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
    <div v-if="isComposite" class="card mb-6">
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

    <!-- Custom request headers (HTTP-like checks) -->
    <div v-if="isHttpLike && monitor.custom_headers && Object.keys(monitor.custom_headers).length" class="card mb-6">
      <h2 class="text-sm font-semibold text-gray-300 mb-2">{{ t('monitors.customHeaders.title') }}</h2>
      <div class="flex flex-wrap gap-2">
        <span v-for="(val, key) in monitor.custom_headers" :key="key"
              class="text-xs font-mono px-2 py-1 rounded bg-gray-800 text-gray-300 border border-gray-700">
          <span class="text-emerald-400">{{ key }}</span>: {{ val }}
        </span>
      </div>
    </div>

    <!-- SSL card (HTTP checks only) -->
    <div v-if="isHttpLike && monitor.ssl_check_enabled && latestSsl" class="card mb-6">
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
    <div v-else-if="isHttpLike && monitor.ssl_check_enabled && !latestSsl" class="card mb-6">
      <div class="flex items-center gap-2 text-gray-500 text-sm">
        <Shield class="w-4 h-4" />
        SSL check enabled — waiting for first result
      </div>
    </div>

    <!-- Domain expiry card -->
    <div v-if="isDomainExpiry" class="card mb-6">
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

    <!-- Incidents + Post-mortem + SLA Report -->
    <MonitorIncidentsTab
      :state="incidentsState"
      :health-state="healthState"
      :fmt-date-time="fmtDateTime"
    />

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
    <div v-if="hasResponseTime" class="card mb-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-300">
          {{ isNetwork ? t('monitor_detail.tcp_latency') : t('monitor_detail.response_time') }}
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
      <p v-else class="text-gray-500 text-sm text-center py-6">{{ t('monitor_detail.no_data') }}</p>
    </div>

    <!-- Response Time Percentiles (P50/P95/P99) -->
    <div v-if="percentilesData.length && hasResponseTime" class="card mb-6">
      <h3 class="text-sm font-semibold text-gray-300 mb-3">{{ t('monitor_detail.percentiles_title') }}</h3>
      <apexchart type="line" height="250" :options="percentileOptions" :series="percentileSeries" />
    </div>

    <!-- SLO panel (legacy SLO + V2 Health Engine) -->
    <MonitorSloPanel
      v-if="monitor"
      :monitor="monitor"
      :state="sloState"
      :has-slo="hasSlo"
      :probe-name="probeName"
    />

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
              {{ fmtDateTime(a.annotated_at) }}
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
    <div v-if="isDns" class="card mb-6">
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
    <div v-if="hasRecentChecks" class="card">
      <h2 class="text-sm font-semibold text-gray-300 mb-4">{{ t('monitor_detail.recent_checks') }}</h2>
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 border-b border-gray-800">
            <th class="pb-2 text-left">Time</th>
            <th class="pb-2 text-left">Probe</th>
            <th class="pb-2 text-left">{{ t('common.status') }}</th>
            <th v-if="!noHttpTypes.includes(monitor.check_type)" class="pb-2 text-left">HTTP</th>
            <th class="pb-2 text-left">Réponse</th>
            <th v-if="isHttpLike" class="pb-2 text-left hidden xl:table-cell">Waterfall</th>
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
            <td v-if="isHttpLike" class="py-2 hidden xl:table-cell">
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

    <!-- ── Onglet Alertes ────────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_ALERTS && monitor">
      <AlertMatrix :monitor-id="monitor.id" :check-type="monitor.check_type" />
    </div>

    <!-- ── Onglet Métriques ──────────────────────────────────────────────────── -->
    <div v-if="activeTab === TAB_METRICS && monitor">
      <MetricsDashboard :monitor-id="String(monitor.id)" />
    </div>

    <!-- ── Onglet Runbook ───────────────────────────────────────────────────── -->
    <MonitorRunbookTab
      v-if="activeTab === TAB_RUNBOOK && monitor"
      :monitor="monitor"
      :editing="runbookEditing"
      v-model:draft="runbookDraft"
      :saving="runbookSaving"
      :rendered-html="runbookRenderedHtml"
      :preview-html="runbookPreviewHtml"
      @start-edit="startEditRunbook"
      @cancel-edit="cancelEditRunbook"
      @save="saveRunbook"
    />

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
        <img :src="screenshotModal.src" :alt="screenshotModal.label || 'Scenario screenshot'" class="w-full rounded-lg border border-gray-700 shadow-2xl" />
      </div>
    </div>
    <EditMonitorModal v-if="editingMonitor" :monitor="editingMonitor" @close="editingMonitor = null" @updated="onMonitorUpdated" />
    <CreateMonitorModal v-if="showClone" :initial-data="clonePayload" @close="showClone = false" @created="onCloneCreated" />

    <!-- Quick schedule maintenance modal -->
    <BaseModal v-model="showMaintenanceModal" :title="t('maintenance.schedule_maintenance')" size="lg">
      <div class="space-y-4">
        <div>
          <label class="text-sm text-gray-400">{{ t('common.name') }} <span class="text-red-400">*</span></label>
          <input v-model="maintForm.name" class="input w-full mt-1" :placeholder="t('maintenance.name_placeholder')" />
        </div>
        <div>
          <label class="text-sm text-gray-400">
            {{ t('maintenance.description_label') }}
            <span class="text-gray-600">({{ t('common.optional') }})</span>
          </label>
          <textarea v-model="maintForm.description" class="input w-full mt-1 resize-none" rows="2"
            :placeholder="t('maintenance.description_placeholder')" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.starts') }} <span class="text-red-400">*</span></label>
            <input v-model="maintForm.starts_at" type="datetime-local" class="input w-full mt-1" />
          </div>
          <div>
            <label class="text-sm text-gray-400">{{ t('maintenance.ends') }} <span class="text-red-400">*</span></label>
            <input v-model="maintForm.ends_at" type="datetime-local" class="input w-full mt-1" />
          </div>
        </div>
        <div class="flex items-center gap-3 py-1">
          <button type="button" @click="maintForm.suppress_alerts = !maintForm.suppress_alerts"
            class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
            :class="maintForm.suppress_alerts ? 'bg-blue-600' : 'bg-gray-700'">
            <span class="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200"
              :class="maintForm.suppress_alerts ? 'translate-x-4' : 'translate-x-0'" />
          </button>
          <span class="text-sm text-gray-300 cursor-pointer select-none"
            @click="maintForm.suppress_alerts = !maintForm.suppress_alerts">
            {{ t('maintenance.suppress_alerts_label') }}
          </span>
        </div>
      </div>
      <template #footer>
        <button @click="showMaintenanceModal = false" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button @click="createMaintWindow" :disabled="maintSaving" class="btn-primary flex-1 disabled:opacity-50">
          {{ maintSaving ? t('common.loading') : t('common.add') }}
        </button>
      </template>
    </BaseModal>
  </div>
  <div v-else class="page-body" role="status" aria-busy="true" :aria-label="t('common.loading')">
    <!-- Skeleton header -->
    <div class="flex items-center gap-4 mb-8">
      <div class="flex-1 space-y-2">
        <SkeletonBox width="14rem" height="1.5rem" />
        <SkeletonBox width="20rem" height="0.75rem" />
      </div>
    </div>
    <!-- Skeleton tabs -->
    <div class="flex gap-3 mb-6 border-b border-gray-800 pb-2">
      <SkeletonBox v-for="i in 4" :key="i" width="5rem" height="1rem" />
    </div>
    <!-- Skeleton chart + cards -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div v-for="i in 3" :key="i" class="card">
        <SkeletonBox width="40%" height="0.7rem" />
        <div class="mt-3"><SkeletonBox width="60%" height="1.5rem" /></div>
      </div>
    </div>
    <div class="card">
      <SkeletonBox width="30%" height="0.85rem" />
      <div class="mt-4"><SkeletonBox width="100%" height="14rem" rounded="md" /></div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Shield, ShieldAlert, ShieldCheck, Copy, CalendarClock } from 'lucide-vue-next'
import { useToast } from '../composables/useToast'
import api from '../api/client'
import { monitorsApi, triggerCheck } from '../api/monitors'
import { probesApi } from '../api/probes'
import MonitorDependencies from '../components/monitors/MonitorDependencies.vue'
import EditMonitorModal from '../components/monitors/EditMonitorModal.vue'
import CreateMonitorModal from '../components/monitors/CreateMonitorModal.vue'
import UptimeHeatmap from '../components/monitors/UptimeHeatmap.vue'
import UptimeViewSplit from '../components/monitors/UptimeViewSplit.vue'
import AlertMatrix from '../components/monitors/AlertMatrix.vue'
import TagChips from '../components/monitors/TagChips.vue'
import MetricsDashboard from '../components/monitors/MetricsDashboard.vue'
import BaseModal from '../components/BaseModal.vue'
import SkeletonBox from '../components/shared/SkeletonBox.vue'
import { useCommandPaletteStore } from '../stores/commandPalette'
import { maintenanceApi } from '../api/maintenance'
import { useTimezone } from '../composables/useTimezone'
import { useMonitorRunbook } from '../composables/useMonitorRunbook'
import { useMonitorDependencies } from '../composables/useMonitorDependencies'
import { useMonitorIncidents } from '../composables/useMonitorIncidents'
import { useMonitorSlo } from '../composables/useMonitorSlo'
import { useMonitorTabs } from '../composables/useMonitorTabs'
import { useMonitorAnnotations } from '../composables/useMonitorAnnotations'
import { useMonitorPercentiles } from '../composables/useMonitorPercentiles'
import { useMonitorCustomMetrics } from '../composables/useMonitorCustomMetrics'
import { useMonitorCharts, PROBE_COLORS } from '../composables/useMonitorCharts'
import { useMonitorDns } from '../composables/useMonitorDns'
import { useMonitorAlerts } from '../composables/useMonitorAlerts'
import { useMonitorTesting } from '../composables/useMonitorTesting'
import { useMonitorMap } from '../composables/useMonitorMap'
import MonitorRunbookTab from '../components/monitors/detail/MonitorRunbookTab.vue'
import MonitorIncidentsTab from '../components/monitors/detail/MonitorIncidentsTab.vue'
import MonitorSloPanel from '../components/monitors/detail/MonitorSloPanel.vue'
import MonitorScenarioTab from '../components/monitors/detail/MonitorScenarioTab.vue'

const { t, locale } = useI18n()
const { error: toastError, success: toastSuccess } = useToast()
const { format: tzFormat } = useTimezone()
// Template shortcut — respects the user's timezone preference (T1-13).
// Drop-in replacement for `new Date(x).toLocaleString(locale)` inline calls.
const fmtDateTime = (v) =>
  v
    ? tzFormat(
        v,
        { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' },
        locale.value,
      )
    : ''

const route = useRoute()
const router = useRouter()
const paletteStore = useCommandPaletteStore()
const monitor   = ref(null)
const results   = ref([])
const uptime24  = ref(null)
const uptime7d  = ref(null)
const probeMap  = ref({})   // probeId → { name, location_name }
const editingMonitor = ref(null)
const showClone = ref(false)
const clonePayload = ref(null)

// ── Maintenance quick-schedule ─────────────────────────────────────────────
const showMaintenanceModal = ref(false)
const maintSaving = ref(false)
const maintForm = ref({
  name: '',
  description: '',
  starts_at: '',
  ends_at: '',
  suppress_alerts: true,
})

function openScheduleMaintenance() {
  const pad = n => String(n).padStart(2, '0')
  const toLocalDt = (d) =>
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
  const now  = new Date()
  const end  = new Date(now.getTime() + 2 * 60 * 60 * 1000) // default 2h window
  maintForm.value = {
    name:            monitor.value ? `${monitor.value.name} — maintenance` : '',
    description:     '',
    starts_at:       toLocalDt(now),
    ends_at:         toLocalDt(end),
    suppress_alerts: true,
  }
  showMaintenanceModal.value = true
}

async function createMaintWindow() {
  if (!maintForm.value.name.trim() || !maintForm.value.starts_at || !maintForm.value.ends_at) {
    toastError(t('maintenance.error_required'))
    return
  }
  maintSaving.value = true
  try {
    await maintenanceApi.create({
      name:            maintForm.value.name.trim(),
      description:     maintForm.value.description || null,
      monitor_id:      monitor.value?.id ?? null,
      group_id:        null,
      starts_at:       new Date(maintForm.value.starts_at).toISOString(),
      ends_at:         new Date(maintForm.value.ends_at).toISOString(),
      suppress_alerts: maintForm.value.suppress_alerts,
    })
    showMaintenanceModal.value = false
    toastSuccess(t('common.success'))
  } catch (err) {
    toastError(t('common.error'))
    if (import.meta.env.DEV) console.error(err)
  } finally {
    maintSaving.value = false
  }
}

function duplicateMonitor() {
  if (!monitor.value) return
  const m = { ...monitor.value }
  // Strip server-only / identity fields
  delete m.id
  delete m.created_at
  delete m.updated_at
  delete m.owner_id
  delete m.heartbeat_slug
  delete m.last_status
  delete m.is_paused
  delete m.group_id
  m.name = 'Copy of ' + m.name
  clonePayload.value = m
  showClone.value = true
}

function onCloneCreated() {
  showClone.value = false
  router.push('/monitors')
}

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
  loadPercentiles()
  loadHealthEngine(id)
}

// ── SLO panel (legacy SLO + V2 Health Engine) ────────────────────────────
const sloState = useMonitorSlo(monitor)
const {
  sloRules,
  healthState,
  loadHealthEngine,
  loadSlo,
  sloEditTarget,
  sloEditDays,
} = sloState

// ── Incidents + Post-mortem + SLA Report ─────────────────────────────────────
const monitorIdRef = computed(() => route.params.id)
const incidentsState = useMonitorIncidents(monitor, monitorIdRef)
const {
  incidents,
  incidentError,
  expandedIncident,
  incidentUpdates,
  incidentUpdatesLoading,
  newUpdate,
  viewMode,
  selectedIncidentId,
  selectedIncident,
  timelineLayout,
  tooltipFor,
  selectIncident,
  toggleIncidentUpdates,
  postIncidentUpdate,
  deleteIncidentUpdate,
  loadIncidents,
  downloadIncidentsCsv,
  postmortem,
  openPostmortem,
  downloadPostmortem,
  slaFrom,
  slaTo,
  slaLoading,
  slaResult,
  downloadSlaReport,
} = incidentsState

// ── Annotations ───────────────────────────────────────────────────────────────
const {
  annotations,
  showForm: showAnnForm,
  newAnnotation,
  load: loadAnnotations,
  add: addAnnotation,
  remove: removeAnnotation,
} = useMonitorAnnotations(monitorIdRef)

// Percentiles P50/P95/P99 — instantiated below, after chartWindow is declared.

// "Tester maintenant" — trigger check + 30s polling: instantiated below,
// after chartWindow is declared.


// ── Scenario run selection ────────────────────────────────────────────────────
const selectedRunId = ref(null)

// ── Map (Carte tab) — Leaflet lazy-loaded on first activation ───────────────
const {
  probeMapEl,
  probeStatuses,
  probesWithCoords,
  probesWithoutCoords,
  markerColor,
  statusLabel,
  loadAndInit: loadAndInitMap,
} = useMonitorMap(monitorIdRef)

const probeColors = PROBE_COLORS

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

// ── DNS (changelog, baseline, drift toggles, alert-suggestion modal) ─────────
const {
  changelog: dnsChangelog,
  isValueChange: isDnsValueChange,
  currentValues: currentDnsValues,
  baselineLoading: dnsBaselineLoading,
  baselineMsg: dnsBaselineMsg,
  acceptBaseline: acceptDnsBaseline,
  resetBaseline: resetDnsBaseline,
  alertModal: dnsAlertModal,
  alertChannels: dnsAlertChannels,
  alertChannelId: dnsAlertChannelId,
  alertCreating: dnsAlertCreating,
  toggleSetting: toggleDnsSetting,
  createAlertRule: createDnsAlertRule,
} = useMonitorDns(monitor, results)

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

// ── "Tester maintenant" — trigger check + 30s polling ───────────────────────
const {
  testing,
  testingState,
  newResultId,
  testingElapsed,
  loadResults,
  handleTriggerCheck,
} = useMonitorTesting(monitor, monitorIdRef, results, chartWindow)

// Reload results when chart window changes (watch must be after chartWindow declaration)
watch(chartWindow, () => { loadResults(); loadPercentiles() })

// ── Alert rules + auto-alert "no rules" banner setup ────────────────────────
const {
  rules: alertRules,
  rulesLoaded: alertRulesLoaded,
  loadRules: loadAlertRules,
  showAutoModal: showAutoAlertModal,
  autoChannels: autoAlertChannels,
  autoSelectedChannels: autoAlertSelectedChannels,
  autoCreating: autoAlertCreating,
  createAutoRules: createAutoAlertRules,
} = useMonitorAlerts(monitor)

// ── Charts (RT line + Availability bar) ──────────────────────────────────────
const {
  rtThresholdMs,
  rtSeries,
  rtOptions,
  availSeries,
  availOptions,
  chartBucketMin,
} = useMonitorCharts({
  results,
  incidents,
  annotations,
  alertRules,
  chartWindow,
  probeName,
})

// ── Custom metrics push ───────────────────────────────────────────────────────
const apiBase = window.location.origin
const {
  metrics: customMetrics,
  showPushUrlModal,
  names: customMetricNames,
  unit: customMetricUnit,
  series: customMetricSeries,
  options: customMetricOptions,
  load: loadCustomMetrics,
} = useMonitorCustomMetrics(monitor)

// ── Percentiles P50/P95/P99 ──────────────────────────────────────────────────
const {
  data: percentilesData,
  load: loadPercentiles,
  series: percentileSeries,
  options: percentileOptions,
} = useMonitorPercentiles(monitorIdRef, chartWindow)

// ── Tabs ─────────────────────────────────────────────────────────────────────
const {
  TAB_AVAILABILITY,
  TAB_SCENARIO,
  TAB_MAP,
  TAB_ALERTS,
  TAB_METRICS,
  TAB_RUNBOOK,
  activeTab,
  viewTabs,
  tabLabel,
  setTab,
} = useMonitorTabs(monitor, customMetrics, { onMapActivated: loadAndInitMap })


// ── Helpers ───────────────────────────────────────────────────────────────────
const noHttpTypes = ['tcp', 'udp', 'smtp', 'ping', 'domain_expiry', 'heartbeat', 'composite']

// ── Check type groups (controls section visibility) ─────────────────────────
const ct = computed(() => monitor.value?.check_type)
const isHttpLike = computed(() => ['http', 'keyword', 'json_path'].includes(ct.value))
const isNetwork = computed(() => ['tcp', 'udp', 'smtp', 'ping'].includes(ct.value))
const isDns = computed(() => ct.value === 'dns')
const isHeartbeat = computed(() => ct.value === 'heartbeat')
const isScenario = computed(() => ct.value === 'scenario')
const isComposite = computed(() => ct.value === 'composite')
const isDomainExpiry = computed(() => ct.value === 'domain_expiry')
// Has response time data (chart + percentiles + stats cards)
const hasResponseTime = computed(() => isHttpLike.value || isNetwork.value)
// Has network scope selector
const hasNetworkScope = computed(() => isHttpLike.value || isNetwork.value || isDns.value)
// Has recent checks table
const hasRecentChecks = computed(() => isHttpLike.value || isNetwork.value)
// Has SLO
const hasSlo = computed(() => isHttpLike.value || isNetwork.value || isDns.value)

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
  return tzFormat(dt, {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    day: '2-digit', month: '2-digit',
  }, locale.value)
}

function formatDateShort(dt) {
  return new Date(dt).toLocaleDateString(locale.value, { day: '2-digit', month: '2-digit', year: 'numeric' })
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
    toastError(e.response?.data?.detail || 'Error accepting baseline')
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

// ── Tags change handler (optimistic, rolls back on failure) ─────────────────
async function onTagsChange(newTags) {
  const previous = monitor.value.tags || []
  monitor.value.tags = newTags
  try {
    await monitorsApi.update(monitor.value.id, { tag_ids: newTags.map(t => t.id) })
  } catch (e) {
    monitor.value.tags = previous
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

// ── Runbook ──────────────────────────────────────────────────────────────────
const {
  editing: runbookEditing,
  draft: runbookDraft,
  saving: runbookSaving,
  renderedHtml: runbookRenderedHtml,
  previewHtml: runbookPreviewHtml,
  startEdit: startEditRunbook,
  cancelEdit: cancelEditRunbook,
  save: saveRunbook,
} = useMonitorRunbook(monitor)

// ── Dependencies & composite members ─────────────────────────────────────────
const {
  allMonitors,
  compositeMembers,
  newMember,
  availableMonitors,
  memberName,
  loadAllMonitors,
  loadCompositeMembers,
  addCompositeMember,
  removeCompositeMember,
} = useMonitorDependencies(monitor)

// (Cleanup handled by useMonitorTesting + useMonitorMap via onScopeDispose.)

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

  // Surface this monitor as a recent in the command palette (T1-10).
  paletteStore.recordVisit({
    type: 'monitor',
    id: monitor.value.id,
    name: monitor.value.name,
    route: `/monitors/${monitor.value.id}`,
  })

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
  loadAllMonitors()

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

.runbook-preview { line-height: 1.55; }
.runbook-preview :deep(h1),
.runbook-preview :deep(h2),
.runbook-preview :deep(h3) { margin: .6rem 0 .35rem; color: var(--text-1); font-weight: 600; }
.runbook-preview :deep(h1) { font-size: 1.05rem; }
.runbook-preview :deep(h2) { font-size: .95rem; }
.runbook-preview :deep(h3) { font-size: .9rem; }
.runbook-preview :deep(p) { margin: .35rem 0; }
.runbook-preview :deep(ul),
.runbook-preview :deep(ol) { padding-left: 1.25rem; margin: .3rem 0; }
.runbook-preview :deep(li) { margin: .2rem 0; }
.runbook-preview :deep(code) {
  background: rgba(255,255,255,.08);
  padding: .1em .35em;
  border-radius: 3px;
  font-size: .85em;
}
.runbook-preview :deep(pre) {
  background: rgba(0,0,0,.4);
  padding: .7rem .9rem;
  border-radius: 6px;
  overflow-x: auto;
  margin: .4rem 0;
}
.runbook-preview :deep(a) { color: #60a5fa; text-decoration: underline; }
.runbook-preview :deep(.runbook-task) { list-style: none; margin-left: -1rem; }
.runbook-preview :deep(.runbook-task input[type="checkbox"]) { margin-right: .45rem; }
</style>
