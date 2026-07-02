<template>
  <div class="p-8">
    <h1 class="font-display text-2xl font-bold text-(--text-1) mb-8">{{ t('alerts.title') }}</h1>

    <!-- Skeleton loading -->
    <div v-if="loading" class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
      <div>
        <div class="skeleton h-6 w-40 mb-4" />
        <div class="space-y-3">
          <div v-for="i in 3" :key="i" class="skeleton-row card">
            <div class="skeleton-circle" />
            <div class="flex-1 space-y-2">
              <div class="skeleton-line w-3/4" />
              <div class="skeleton-line w-1/2" style="height:0.5rem" />
            </div>
          </div>
        </div>
      </div>
      <div>
        <div class="skeleton h-6 w-40 mb-4" />
        <div class="space-y-2">
          <div v-for="i in 5" :key="i" class="card py-2.5">
            <div class="skeleton-line w-full" />
            <div class="skeleton-line w-2/3 mt-2" style="height:0.5rem" />
          </div>
        </div>
      </div>
    </div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
      <!-- Alert Channels -->
      <div>
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-(--text-1)">{{ t('alerts.channels') }}</h2>
          <button @click="showAddChannel = true" class="btn-primary">+ {{ t('alerts.add_channel') }}</button>
        </div>
        <div class="space-y-3">
          <div v-for="(channel, idx) in channels" :key="channel.id" class="card stagger-item" :style="{ animationDelay: idx * 50 + 'ms' }">
            <div class="flex items-center gap-4">
              <div class="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
                :class="channelIcon(channel.type).bg">
                {{ channelIcon(channel.type).emoji }}
              </div>
              <div class="flex-1 min-w-0">
                <p class="font-medium text-(--text-1) truncate">{{ channel.name }}</p>
                <p class="text-xs text-(--text-3) capitalize">{{ channel.type }}</p>
              </div>
              <!-- Last activity badge -->
              <div v-if="lastActivityByChannel[channel.id]" class="text-right flex-shrink-0 hidden sm:block">
                <span class="text-xs" :class="lastActivityByChannel[channel.id].status === 'sent' ? 'text-(--up)' : 'text-(--down)'">
                  {{ lastActivityByChannel[channel.id].status === 'sent' ? '✓' : '✗' }}
                  {{ formatRelative(lastActivityByChannel[channel.id].sent_at) }}
                </span>
              </div>
              <!-- Test button -->
              <button
                @click="testChannel(channel)"
                :disabled="testingChannel === channel.id"
                class="text-xs px-2 py-1 rounded-lg border border-(--border) text-(--text-2) hover:border-(--accent-border) hover:text-(--accent) transition-colors flex-shrink-0 disabled:opacity-50"
              >
                {{ testingChannel === channel.id ? t('alerts.test_channel_running') : t('alerts.test_channel') }}
              </button>
              <button @click="confirmDeleteChannel(channel)" class="text-(--text-3) hover:text-(--down) transition-colors flex-shrink-0" :aria-label="t('common.delete')">✕</button>
            </div>
            <!-- Test result inline -->
            <div v-if="testResults[channel.id]" class="mt-2 text-xs px-3 py-1.5 rounded-lg"
              :class="testResults[channel.id].success ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up) border border-[color-mix(in_srgb,var(--up)_35%,transparent)]' : 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down) border border-[color-mix(in_srgb,var(--down)_35%,transparent)]'">
              {{ testResults[channel.id].success ? t('alerts.test_channel_success') : t('alerts.test_channel_failed') }}
              — {{ testResults[channel.id].detail }}
            </div>
          </div>
          <EmptyState
            v-if="!channels.length"
            :title="t('alerts.no_channels')"
            :text="t('empty.alerts_channels_text')"
            :cta-label="t('alerts.add_channel')"
            doc-href="https://github.com/AurevLan/whatisup#alert-channels"
            @cta="showAddChannel = true"
          >
            <template #icon><Bell :size="22" /></template>
          </EmptyState>
        </div>
      </div>

      <!-- Recent Alert Events -->
      <div>
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-(--text-1)">{{ t('alerts.recent_events') }}</h2>
          <!-- Filter tabs -->
          <div class="flex gap-1 bg-(--bg-surface-2) rounded-lg p-0.5">
            <button v-for="f in eventFilters" :key="f.value"
              @click="eventsFilter = f.value"
              class="text-xs px-2.5 py-1 rounded-md transition-colors"
              :class="eventsFilter === f.value ? 'bg-(--bg-surface-2) text-(--text-1)' : 'text-(--text-3) hover:text-(--text-1)'">
              {{ f.label }}
            </button>
          </div>
        </div>
        <div class="space-y-2">
          <div v-for="event in filteredEvents" :key="event.id" class="card py-2.5">
            <div class="flex items-center gap-3">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                :class="event.status === 'sent' ? 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)] text-(--up)' : 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] text-(--down)'">
                {{ event.status }}
              </span>
              <span class="text-xs text-(--text-2) flex-shrink-0">{{ formatDate(event.sent_at) }}</span>
              <span class="text-xs text-(--text-3) truncate font-mono">{{ channelName(event.channel_id) }}</span>
            </div>
            <div class="flex items-center gap-2 mt-1">
              <p v-if="event.monitor_name" class="text-xs text-(--text-2) font-medium truncate">
                {{ event.monitor_name }}
              </p>
              <p v-else class="text-xs text-(--text-3) font-mono">Incident {{ event.incident_id.slice(0, 8) }}…</p>
              <span v-if="event.response_body && event.response_body !== 'null'" class="text-xs text-(--text-3) truncate">
                · {{ event.response_body }}
              </span>
            </div>
          </div>
          <EmptyState
            v-if="!filteredEvents.length"
            :title="t('alerts.no_events')"
            :text="t('empty.alerts_events_text')"
            inline
          >
            <template #icon><ClipboardList :size="22" /></template>
          </EmptyState>
        </div>
      </div>
    </div>

    <!-- Threshold suggestions -->
    <div v-if="thresholdSuggestions.length > 0" class="mb-8">
      <h2 class="text-lg font-semibold text-(--text-1) mb-3">{{ t('alerts.suggestions_title') }}</h2>
      <div class="space-y-2">
        <div v-for="s in thresholdSuggestions" :key="s.monitor_id"
          class="card flex items-center justify-between gap-4">
          <div class="flex-1 min-w-0">
            <p class="text-sm text-(--text-1) font-medium truncate">{{ s.monitor_name }}</p>
            <p class="text-xs text-(--text-3)">
              p95 = {{ s.p95_ms }}ms · {{ t('alerts.suggested_threshold', { ms: s.suggested_threshold_ms }) }}
            </p>
          </div>
          <button
            @click="applySuggestion(s)"
            :disabled="applyingSuggestion === s.monitor_id"
            class="btn-primary btn-sm whitespace-nowrap disabled:opacity-50"
          >{{ t('alerts.apply_suggestion') }}</button>
          <button @click="dismissSuggestion(s)" class="text-(--text-3) hover:text-(--text-2) text-xs" :aria-label="t('common.dismiss')">✕</button>
        </div>
      </div>
    </div>

    <!-- Alert Rules -->
    <div>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-(--text-1)">{{ t('alerts.title') }}</h2>
        <button @click="openCreateRule" :disabled="!channels.length" class="btn-primary disabled:opacity-40 disabled:cursor-not-allowed">
          + {{ t('alerts.add_rule') }}
        </button>
      </div>
      <p v-if="!channels.length" class="text-xs text-(--warn) mb-3">
        ⚠ {{ t('alerts.create_channel_first') }}
      </p>

      <div v-if="rules.length === 0 && channels.length" class="text-(--text-3) text-sm text-center py-8">
        {{ t('alerts.no_rules') }}
      </div>

      <div class="space-y-3">
        <div v-for="rule in rules" :key="rule.id" class="card" :class="!rule.enabled ? 'opacity-60' : ''">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium text-(--text-1)">{{ targetName(rule) }}</span>
                <span class="text-xs px-2 py-0.5 rounded-full font-mono"
                  :class="rule.monitor_id ? 'bg-(--accent-glow) text-(--accent)' : 'bg-(--accent-glow) text-(--accent)'">
                  {{ rule.monitor_id ? t('alerts.scope_monitor') : t('alerts.scope_group') }}
                </span>
                <span v-if="!rule.enabled" class="text-xs px-2 py-0.5 rounded-full bg-(--bg-surface-2) text-(--text-3)">
                  {{ t('alerts.rule_disabled') }}
                </span>
              </div>
              <div class="mt-2 flex items-center gap-2 flex-wrap">
                <span class="text-xs px-2 py-0.5 rounded-full bg-(--bg-surface-2) text-(--text-2) font-mono">
                  {{ conditionLabel(rule.condition) }}
                  <span v-if="rule.threshold_value != null">{{ conditionUnit(rule.condition, rule.threshold_value) }}</span>
                </span>
                <span v-if="rule.min_duration_seconds" class="text-xs text-(--text-3)">{{ t('alerts.rule_after_seconds', { n: rule.min_duration_seconds }) }}</span>
                <span v-if="rule.renotify_after_minutes" class="text-xs text-(--text-3)">{{ t('alerts.rule_renotify_minutes', { n: rule.renotify_after_minutes }) }}</span>
                <span v-if="rule.digest_minutes" class="text-xs text-(--accent)">{{ t('alerts.rule_digest_minutes', { n: rule.digest_minutes }) }}</span>
                <span v-if="rule.anomaly_zscore_threshold" class="text-xs text-(--accent)">· z={{ rule.anomaly_zscore_threshold }}</span>
                <span v-if="rule.schedule?.offhours_suppress" class="text-xs text-(--warn)">{{ t('alerts.rule_business_hours') }}</span>
              </div>
              <div class="mt-2 flex items-center gap-1.5 flex-wrap">
                <span v-for="ch in rule.channels" :key="ch.id"
                  class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-(--bg-surface-2) text-(--text-2)">
                  {{ channelIcon(ch.type).emoji }} {{ ch.name }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-2 flex-shrink-0">
              <!-- Simulate -->
              <button @click="runSimulate(rule)"
                :disabled="simulatingRule === rule.id"
                class="text-xs px-2 py-1 rounded-lg border border-(--border) text-(--text-2) hover:border-(--accent-border) hover:text-(--accent) transition-colors disabled:opacity-50">
                {{ simulatingRule === rule.id ? t('alerts.simulate_running') : t('alerts.simulate') }}
              </button>
              <!-- Enable/disable toggle -->
              <button @click="toggleRule(rule)"
                :title="rule.enabled ? t('alerts.rule_enabled') : t('alerts.rule_disabled')"
                :aria-label="rule.enabled ? t('alerts.rule_enabled') : t('alerts.rule_disabled')"
                class="text-xs px-2 py-1 rounded-lg border transition-colors"
                :class="rule.enabled
                  ? 'border-[color-mix(in_srgb,var(--up)_35%,transparent)] text-(--up) hover:border-(--down) hover:text-(--down)'
                  : 'border-(--border) text-(--text-3) hover:border-(--up) hover:text-(--up)'">
                {{ rule.enabled ? '●' : '○' }}
              </button>
              <!-- Edit -->
              <button @click="openEditRule(rule)"
                class="text-xs px-2 py-1 rounded-lg border border-(--border) text-(--text-2) hover:border-(--border-hover) hover:text-(--text-1) transition-colors">
                {{ t('common.edit') }}
              </button>
              <!-- Delete -->
              <button @click="confirmDeleteRule(rule)" class="text-(--text-3) hover:text-(--down) transition-colors" :aria-label="t('common.delete')">✕</button>
            </div>
          </div>

          <!-- Simulate result -->
          <div v-if="simulateResults[rule.id]" class="mt-3 text-xs px-3 py-2 rounded-lg border"
            :class="simulateResults[rule.id].would_fire
              ? 'bg-[color-mix(in_srgb,var(--down)_15%,transparent)] border-[color-mix(in_srgb,var(--down)_35%,transparent)] text-(--down)'
              : 'bg-(--bg-surface-2) border-(--border) text-(--text-2)'">
            <span class="font-medium">
              {{ simulateResults[rule.id].would_fire ? t('alerts.simulate_would_fire') : t('alerts.simulate_would_not_fire') }}
            </span>
            — {{ simulateResults[rule.id].reason }}
          </div>
        </div>
      </div>
    </div>

    <!-- Alerting Templates (superadmin) -->
    <div v-if="isSuperadmin" class="mt-10">
      <AlertTemplatesSection />
    </div>

    <!-- Add/Edit Rule Modal -->
    <BaseModal :model-value="showRuleModal" size="lg"
      :title="editingRule ? t('alerts.edit_rule') : t('alerts.add_rule')"
      @close="closeRuleModal">
      <form @submit.prevent="saveRule" class="space-y-4">
          <!-- Target type (only for create) -->
          <div v-if="!editingRule">
            <label class="block text-sm font-medium text-(--text-2) mb-2">{{ t('alerts.target_label') }} *</label>
            <div class="grid grid-cols-2 gap-2 mb-2">
              <button type="button" @click="ruleForm.target_type = 'monitor'; ruleForm.target_id = ''"
                class="py-2 px-3 rounded-lg border text-sm font-medium transition-colors"
                :class="ruleForm.target_type === 'monitor'
                  ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
                  : 'border-(--border) text-(--text-2) hover:border-(--border-hover)'">
                {{ t('alerts.target_monitor') }}
              </button>
              <button type="button" @click="ruleForm.target_type = 'group'; ruleForm.target_id = ''"
                class="py-2 px-3 rounded-lg border text-sm font-medium transition-colors"
                :class="ruleForm.target_type === 'group'
                  ? 'bg-(--accent-glow) border-(--accent-border) text-(--accent)'
                  : 'border-(--border) text-(--text-2) hover:border-(--border-hover)'">
                {{ t('alerts.target_group') }}
              </button>
            </div>
            <select v-model="ruleForm.target_id" class="input w-full" required>
              <option value="">{{ t('alerts.select_placeholder') }}</option>
              <template v-if="ruleForm.target_type === 'monitor'">
                <option v-for="m in allMonitors" :key="m.id" :value="m.id">
                  {{ m.name }} ({{ m.check_type }})
                </option>
              </template>
              <template v-else>
                <option v-for="g in allGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
              </template>
            </select>
          </div>
          <!-- Show current target for edit -->
          <div v-else>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.target_label') }}</label>
            <p class="text-sm text-(--text-2) px-3 py-2 bg-(--bg-surface-2) rounded-lg">
              {{ targetName(editingRule) }}
              <span class="text-(--text-3) ml-2 text-xs">{{ t('alerts.target_locked') }}</span>
            </p>
          </div>

          <!-- Condition -->
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.condition_label') }} *</label>
            <select v-model="ruleForm.condition" class="input w-full" required>
              <option value="any_down">{{ t('alerts.cond_any_down') }}</option>
              <option value="all_down">{{ t('alerts.cond_all_down') }}</option>
              <option value="ssl_expiry">{{ t('alerts.cond_ssl_expiry') }}</option>
              <option value="response_time_above">{{ t('alerts.cond_response_time_above') }}</option>
              <option value="response_time_above_baseline">{{ t('alerts.cond_response_time_above_baseline') }}</option>
              <option value="anomaly_detection">{{ t('alerts.cond_anomaly_detection') }}</option>
              <option value="schema_drift">{{ t('alerts.cond_schema_drift') }}</option>
            </select>
          </div>

          <!-- Baseline factor -->
          <div v-if="ruleForm.condition === 'response_time_above_baseline'" class="bg-(--accent-glow) border border-(--accent-border) rounded-lg p-3 space-y-2">
            <label class="block text-sm font-medium text-(--text-2)">
              {{ t('alerts.baseline_factor_label') }}
              <span class="text-(--text-3) font-normal ml-1">{{ t('alerts.baseline_factor_hint') }}</span>
            </label>
            <input v-model.number="ruleForm.baseline_factor" class="input w-full" type="number" min="1.1" max="20" step="0.1" :placeholder="t('alerts.baseline_placeholder')" />
            <p class="text-xs text-(--text-3)">{{ t('alerts.baseline_factor_help') }}</p>
          </div>

          <!-- Anomaly z-score threshold -->
          <div v-if="ruleForm.condition === 'anomaly_detection'" class="bg-(--accent-glow) border border-(--accent-border) rounded-lg p-3 space-y-2">
            <label class="block text-sm font-medium text-(--text-2)">
              {{ t('alerts.zscore_label') }}
              <span class="text-(--text-3) font-normal ml-1">{{ t('alerts.zscore_hint') }}</span>
            </label>
            <input v-model.number="ruleForm.anomaly_zscore_threshold" class="input w-full" type="number" min="1.0" max="10.0" step="0.1" placeholder="3.5" />
            <p class="text-xs text-(--text-3)">{{ t('alerts.zscore_help') }}</p>
          </div>

          <!-- Schema drift info + inverse bridge: a schema_drift rule does nothing
               unless the monitor actually computes the fingerprint, so offer to
               enable detection right here instead of a dead-end hint. -->
          <div v-if="ruleForm.condition === 'schema_drift'" class="bg-[color-mix(in_srgb,var(--warn)_15%,transparent)] border border-[color-mix(in_srgb,var(--warn)_35%,transparent)] rounded-lg p-3 space-y-2">
            <p class="text-xs text-(--warn)">{{ t('alerts.schema_drift_help') }}</p>
            <template v-if="ruleForm.target_type === 'monitor' && selectedMonitor">
              <p v-if="selectedMonitor.schema_drift_enabled" class="text-xs text-(--up)">✓ {{ t('alerts.schema_drift_enabled_ok') }}</p>
              <button v-else type="button" class="btn-secondary btn-sm" :disabled="enablingDrift" @click="enableSchemaDrift">
                {{ enablingDrift ? t('common.loading') : t('alerts.schema_drift_enable_cta') }}
              </button>
            </template>
          </div>

          <!-- Threshold -->
          <div v-if="ruleForm.condition === 'response_time_above'">
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.threshold_ms_label') }} *</label>
            <input v-model.number="ruleForm.threshold_value" class="input w-full" type="number" min="1" max="60000" :placeholder="t('alerts.threshold_placeholder')" required />
          </div>

          <!-- Min duration -->
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">
              {{ t('alerts.min_duration_label') }}
              <span class="text-(--text-3) font-normal">{{ t('alerts.min_duration_hint') }}</span>
            </label>
            <input v-model.number="ruleForm.min_duration_seconds" class="input w-full" type="number" min="0" max="3600" />
          </div>

          <!-- Renotify -->
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">
              {{ t('alerts.renotify_label') }}
              <span class="text-(--text-3) font-normal">{{ t('alerts.renotify_hint') }}</span>
            </label>
            <input v-model.number="ruleForm.renotify_after_minutes" class="input w-full" type="number" min="1" max="10080" :placeholder="t('alerts.renotify_placeholder')" />
          </div>

          <!-- Digest -->
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">
              {{ t('alerts.digest_label') }}
              <span class="text-(--text-3) font-normal">{{ t('alerts.digest_off_hint') }}</span>
            </label>
            <input v-model.number="ruleForm.digest_minutes" class="input w-full" type="number" min="0" max="1440" :placeholder="t('alerts.digest_placeholder')" />
          </div>

          <!-- Business Hours Schedule -->
          <div class="border border-(--border) rounded-lg overflow-hidden">
            <button
              type="button"
              @click="ruleForm.showSchedule = !ruleForm.showSchedule"
              class="w-full flex items-center justify-between px-3 py-2.5 text-sm text-(--text-2) hover:bg-(--bg-surface-2) transition-colors"
            >
              <span class="font-medium">{{ t('alerts.schedule_title') }}</span>
              <span class="text-(--text-3) text-xs">{{ ruleForm.showSchedule ? '▲' : '▼' }}</span>
            </button>
            <div v-if="ruleForm.showSchedule" class="px-3 pb-3 space-y-3 border-t border-(--border) pt-3">
              <p class="text-xs text-(--text-3)">{{ t('alerts.schedule_help') }}</p>

              <div class="flex items-center gap-2">
                <input type="checkbox" id="offhours-suppress" v-model="ruleForm.schedule.offhours_suppress" class="w-4 h-4" />
                <label for="offhours-suppress" class="text-sm text-(--text-2)">{{ t('alerts.schedule_suppress_label') }}</label>
              </div>

              <div v-if="ruleForm.schedule.offhours_suppress" class="space-y-3">
                <div>
                  <label class="block text-xs text-(--text-2) mb-1">{{ t('alerts.schedule_timezone') }}</label>
                  <select v-model="ruleForm.schedule.timezone" class="input w-full text-sm">
                    <option v-for="tz in commonTimezones" :key="tz" :value="tz">{{ tz }}</option>
                  </select>
                </div>

                <div>
                  <label class="block text-xs text-(--text-2) mb-1">{{ t('alerts.schedule_days') }}</label>
                  <div class="flex flex-wrap gap-1">
                    <button
                      v-for="(day, idx) in weekDays"
                      :key="idx"
                      type="button"
                      @click="toggleDay(idx)"
                      class="px-2 py-0.5 rounded text-xs font-medium transition-colors"
                      :class="ruleForm.schedule.days?.includes(idx) ? 'bg-(--accent-glow) text-(--accent)' : 'bg-(--bg-surface-2) text-(--text-2) hover:bg-(--bg-surface-3)'"
                    >{{ day }}</button>
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-2">
                  <div>
                    <label class="block text-xs text-(--text-2) mb-1">{{ t('alerts.schedule_start') }}</label>
                    <input v-model="ruleForm.schedule.start" type="time" class="input w-full text-sm" />
                  </div>
                  <div>
                    <label class="block text-xs text-(--text-2) mb-1">{{ t('alerts.schedule_end') }}</label>
                    <input v-model="ruleForm.schedule.end" type="time" class="input w-full text-sm" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Channels -->
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-2">{{ t('alerts.channels_label') }} *</label>
            <div class="space-y-2">
              <label v-for="ch in channels" :key="ch.id" class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" :value="ch.id" v-model="ruleForm.channel_ids" class="w-4 h-4" />
                <span class="text-sm text-(--text-2)">
                  {{ channelIcon(ch.type).emoji }} {{ ch.name }}
                  <span class="text-(--text-3) text-xs capitalize">({{ ch.type }})</span>
                </span>
              </label>
            </div>
          </div>

          <!-- Message preview -->
          <div v-if="ruleForm.condition && ruleForm.channel_ids.length" class="bg-(--bg-surface-2) border border-(--border) rounded-lg p-3">
            <p class="text-xs text-(--text-3) mb-1.5 font-medium uppercase tracking-wide">{{ t('alerts.preview_title') }}</p>
            <p class="text-xs text-(--text-2) font-mono whitespace-pre-wrap">{{ messagePreview }}</p>
          </div>

          <div v-if="ruleError" class="bg-[color-mix(in_srgb,var(--down)_15%,transparent)] border border-[color-mix(in_srgb,var(--down)_35%,transparent)] rounded p-3 text-sm text-(--down)">
            {{ ruleError }}
          </div>

          <div class="flex gap-3 pt-2">
            <button type="button" @click="closeRuleModal"
              class="flex-1 px-4 py-2 border border-(--border) text-(--text-2) rounded-lg hover:bg-(--bg-surface-2)">
              {{ t('common.cancel') }}
            </button>
            <button type="submit"
              :disabled="ruleLoading || (!editingRule && (!ruleForm.target_id || !ruleForm.channel_ids.length)) || (editingRule && !ruleForm.channel_ids.length)"
              class="flex-1 btn-primary disabled:opacity-40 disabled:cursor-not-allowed">
              {{ ruleLoading ? t('common.loading') : (editingRule ? t('common.save') : t('alerts.add_rule')) }}
            </button>
          </div>
        </form>
    </BaseModal>

    <!-- Add Channel Modal -->
    <AddChannelModal v-if="showAddChannel" @close="showAddChannel = false" @created="loadData" />

    <!-- Confirm delete modal -->
    <BaseModal :model-value="!!confirmModal" size="sm"
      :title="confirmModal?.title ?? ''"
      :message="t('alerts.confirm_delete_detail')"
      @close="confirmModal = null">
      <template #footer>
        <button @click="confirmModal = null" class="flex-1 px-4 py-2 border border-(--border) text-(--text-2) rounded-lg hover:bg-(--bg-surface-2)">
          {{ t('common.cancel') }}
        </button>
        <button @click="confirmModal.action(); confirmModal = null" class="flex-1 px-4 py-2 bg-(--down) hover:brightness-110 text-white rounded-lg">
          {{ t('common.delete') }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'
import { monitorsApi, groupsApi } from '../api/monitors'
import { useToast } from '../composables/useToast'
import { useDateFormat } from '../composables/useDateFormat'
import AddChannelModal from '../components/alerts/AddChannelModal.vue'
import BaseModal from '../components/BaseModal.vue'
import AlertTemplatesSection from '../components/alerts/AlertTemplatesSection.vue'
import EmptyState from '../components/shared/EmptyState.vue'
import { Bell, ClipboardList } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const isSuperadmin = computed(() => authStore.isSuperadmin)

const { t } = useI18n()
const { success, error: toastError } = useToast()
const { formatDate, formatRelative } = useDateFormat()

const loading = ref(true)
const channels = ref([])
const events = ref([])
const rules = ref([])
const allMonitors = ref([])
const allGroups = ref([])
const enablingDrift = ref(false)
const showAddChannel = ref(false)
const showRuleModal = ref(false)
const editingRule = ref(null)
const ruleLoading = ref(false)
const ruleError = ref('')
const testingChannel = ref(null)
const testResults = ref({})
const simulatingRule = ref(null)
const simulateResults = ref({})
const eventsFilter = ref('all')
const confirmModal = ref(null)

// Threshold suggestions (A4)
const thresholdSuggestions = ref([])
const applyingSuggestion = ref(null)

async function loadSuggestions() {
  try {
    const { data } = await api.get('/alerts/suggestions/thresholds')
    thresholdSuggestions.value = data
  } catch {}
}

async function applySuggestion(s) {
  if (!channels.value.length) return
  applyingSuggestion.value = s.monitor_id
  try {
    await api.post('/alerts/rules', {
      monitor_id: s.monitor_id,
      condition: 'response_time_above',
      threshold_value: s.suggested_threshold_ms,
      min_duration_seconds: 0,
      channel_ids: channels.value.map(c => c.id),
    }, { skipErrorToast: true })
    thresholdSuggestions.value = thresholdSuggestions.value.filter(x => x.monitor_id !== s.monitor_id)
    await loadData()
    success(t('alerts.toast_rule_created_for', { name: s.monitor_name, ms: s.suggested_threshold_ms }))
  } catch (err) {
    toastError(err.response?.data?.detail || t('alerts.toast_error_creating_rule'))
  } finally {
    applyingSuggestion.value = null
  }
}

function dismissSuggestion(s) {
  thresholdSuggestions.value = thresholdSuggestions.value.filter(x => x.monitor_id !== s.monitor_id)
}

const DEFAULT_SCHEDULE = { offhours_suppress: false, timezone: 'Europe/Paris', days: [0, 1, 2, 3, 4], start: '09:00', end: '18:00' }

const ruleForm = ref(defaultRuleForm())

// Inverse detection→alert bridge: the monitor selected for a schema_drift rule.
const selectedMonitor = computed(() =>
  ruleForm.value.target_type === 'monitor'
    ? allMonitors.value.find((m) => m.id === ruleForm.value.target_id) || null
    : null,
)

async function enableSchemaDrift() {
  const m = selectedMonitor.value
  if (!m) return
  enablingDrift.value = true
  try {
    await monitorsApi.update(m.id, { schema_drift_enabled: true }, { skipErrorToast: true })
    m.schema_drift_enabled = true
    success(t('alerts.schema_drift_enabled_ok'))
  } catch (e) {
    toastError(e.response?.data?.detail || t('common.error'))
  } finally {
    enablingDrift.value = false
  }
}

function defaultRuleForm() {
  return {
    target_type: 'monitor',
    target_id: '',
    condition: 'any_down',
    threshold_value: null,
    min_duration_seconds: 0,
    renotify_after_minutes: null,
    digest_minutes: 0,
    channel_ids: [],
    anomaly_zscore_threshold: null,
    baseline_factor: null,
    showSchedule: false,
    schedule: { ...DEFAULT_SCHEDULE },
  }
}

const commonTimezones = [
  'Europe/Paris', 'Europe/London', 'Europe/Berlin', 'Europe/Madrid', 'Europe/Rome',
  'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
  'America/Sao_Paulo', 'Asia/Tokyo', 'Asia/Shanghai', 'Asia/Singapore',
  'Asia/Kolkata', 'Australia/Sydney', 'Pacific/Auckland', 'UTC',
]

const weekDays = computed(() =>
  ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'].map((d) => t(`common.weekday_${d}`))
)

function toggleDay(idx) {
  const days = ruleForm.value.schedule.days || []
  const next = days.includes(idx) ? days.filter(d => d !== idx) : [...days, idx]
  ruleForm.value.schedule.days = next.sort((a, b) => a - b)
}

const eventFilters = computed(() => [
  { value: 'all', label: t('alerts.events_filter_all') },
  { value: 'sent', label: t('alerts.events_filter_sent') },
  { value: 'failed', label: t('alerts.events_filter_failed') },
])

const filteredEvents = computed(() => {
  if (eventsFilter.value === 'all') return events.value
  return events.value.filter(e => e.status === eventsFilter.value)
})

const lastActivityByChannel = computed(() => {
  const map = {}
  for (const event of events.value) {
    if (!map[event.channel_id]) {
      map[event.channel_id] = event
    }
  }
  return map
})

const messagePreview = computed(() => {
  const cond = ruleForm.value.condition
  const threshold = ruleForm.value.threshold_value
  const lines = ['[WhatIsUp] 🔴 ALERTE : <Monitor Name>']
  if (cond === 'any_down') lines.push('Panne détectée sur au moins une sonde')
  else if (cond === 'all_down') lines.push('Panne globale — toutes les sondes détectent une panne')
  else if (cond === 'ssl_expiry') lines.push('Expiration du certificat SSL imminente')
  else if (cond === 'response_time_above') lines.push(`Temps de réponse > ${threshold || '…'}ms`)
  else if (cond === 'response_time_above_baseline') lines.push(`Temps de réponse > ${ruleForm.value.baseline_factor || '…'}× la moyenne habituelle (7j)`)
  else if (cond === 'anomaly_detection') lines.push(`Temps de réponse anormal détecté (z-score > ${ruleForm.value.anomaly_zscore_threshold || 3.5})`)
  else if (cond === 'schema_drift') lines.push('La structure de la réponse API a changé')
  lines.push('Début : 2026-01-01 12:00 UTC')
  return lines.join('\n')
})

function channelIcon(type) {
  const map = {
    email:     { emoji: '📧', bg: 'bg-(--accent-glow)' },
    webhook:   { emoji: '🔗', bg: 'bg-(--accent-glow)' },
    telegram:  { emoji: '✈️', bg: 'bg-(--accent-glow)' },
    slack:     { emoji: '💬', bg: 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)]' },
    pagerduty: { emoji: '🔔', bg: 'bg-[color-mix(in_srgb,var(--up)_15%,transparent)]' },
    opsgenie:  { emoji: '🚨', bg: 'bg-[color-mix(in_srgb,var(--warn)_15%,transparent)]' },
  }
  return map[type] || { emoji: '🔔', bg: 'bg-(--bg-surface-2)' }
}

function channelName(channelId) {
  return channels.value.find(c => c.id === channelId)?.name || channelId.slice(0, 8) + '…'
}

function targetName(rule) {
  if (rule.monitor_id) {
    return allMonitors.value.find(m => m.id === rule.monitor_id)?.name || rule.monitor_id.slice(0, 8) + '…'
  }
  return allGroups.value.find(g => g.id === rule.group_id)?.name || rule.group_id?.slice(0, 8) + '…'
}

const CONDITION_KEYS = [
  'any_down', 'all_down', 'ssl_expiry', 'response_time_above',
  'response_time_above_baseline', 'anomaly_detection', 'schema_drift',
]

function conditionLabel(cond) {
  return CONDITION_KEYS.includes(cond) ? t(`alerts.cond_short_${cond}`) : cond
}

function conditionUnit(cond, val) {
  if (cond === 'response_time_above') return ` ${val}ms`
  return ''
}

async function loadData() {
  showAddChannel.value = false
  try {
    const [chResp, evResp, rulesResp] = await Promise.all([
      api.get('/alerts/channels'),
      api.get('/alerts/events'),
      api.get('/alerts/rules'),
    ])
    channels.value = chResp.data
    events.value = evResp.data
    rules.value = rulesResp.data
  } finally {
    loading.value = false
  }
}

function confirmDeleteChannel(channel) {
  confirmModal.value = {
    title: t('alerts.confirm_delete_channel', { name: channel.name }),
    action: async () => {
      await api.delete(`/alerts/channels/${channel.id}`)
      await loadData()
      success(t('alerts.toast_channel_deleted', { name: channel.name }))
    },
  }
}

function confirmDeleteRule(rule) {
  confirmModal.value = {
    title: t('alerts.confirm_delete_rule'),
    action: async () => {
      await api.delete(`/alerts/rules/${rule.id}`)
      await loadData()
      success(t('alerts.toast_rule_deleted'))
    },
  }
}

async function testChannel(channel) {
  testingChannel.value = channel.id
  delete testResults.value[channel.id]
  try {
    const resp = await api.post(`/alerts/channels/${channel.id}/test`)
    testResults.value = { ...testResults.value, [channel.id]: resp.data }
  } catch (err) {
    testResults.value = {
      ...testResults.value,
      [channel.id]: { success: false, detail: err.response?.data?.detail || t('common.network_error') },
    }
  } finally {
    testingChannel.value = null
  }
}

async function toggleRule(rule) {
  await api.patch(`/alerts/rules/${rule.id}`, { enabled: !rule.enabled })
  rule.enabled = !rule.enabled
  success(rule.enabled ? t('alerts.toast_rule_enabled') : t('alerts.toast_rule_disabled'))
}

async function runSimulate(rule) {
  simulatingRule.value = rule.id
  delete simulateResults.value[rule.id]
  try {
    const resp = await api.post(`/alerts/rules/${rule.id}/simulate`)
    simulateResults.value = { ...simulateResults.value, [rule.id]: resp.data }
  } catch (err) {
    simulateResults.value = {
      ...simulateResults.value,
      [rule.id]: { would_fire: false, reason: err.response?.data?.detail || t('common.error'), affected_monitors: [] },
    }
  } finally {
    simulatingRule.value = null
  }
}

function openCreateRule() {
  editingRule.value = null
  ruleForm.value = defaultRuleForm()
  ruleError.value = ''
  showRuleModal.value = true
}

function openEditRule(rule) {
  editingRule.value = rule
  const hasSchedule = !!rule.schedule
  ruleForm.value = {
    target_type: rule.monitor_id ? 'monitor' : 'group',
    target_id: rule.monitor_id || rule.group_id || '',
    condition: rule.condition,
    threshold_value: rule.threshold_value,
    min_duration_seconds: rule.min_duration_seconds,
    renotify_after_minutes: rule.renotify_after_minutes,
    digest_minutes: rule.digest_minutes,
    channel_ids: rule.channels.map(c => c.id),
    anomaly_zscore_threshold: rule.anomaly_zscore_threshold ?? null,
    baseline_factor: rule.baseline_factor ?? null,
    showSchedule: hasSchedule,
    schedule: rule.schedule ? { ...rule.schedule } : { ...DEFAULT_SCHEDULE },
  }
  ruleError.value = ''
  showRuleModal.value = true
}

function closeRuleModal() {
  showRuleModal.value = false
  editingRule.value = null
  ruleError.value = ''
}

async function saveRule() {
  ruleLoading.value = true
  ruleError.value = ''
  const isEditing = !!editingRule.value
  try {
    const schedulePayload = ruleForm.value.schedule?.offhours_suppress
      ? ruleForm.value.schedule
      : null

    if (editingRule.value) {
      const payload = {
        condition: ruleForm.value.condition,
        min_duration_seconds: ruleForm.value.min_duration_seconds || 0,
        channel_ids: ruleForm.value.channel_ids,
        threshold_value: ruleForm.value.threshold_value || undefined,
        renotify_after_minutes: ruleForm.value.renotify_after_minutes || undefined,
        digest_minutes: ruleForm.value.digest_minutes || 0,
        anomaly_zscore_threshold: ruleForm.value.anomaly_zscore_threshold || undefined,
        baseline_factor: ruleForm.value.baseline_factor || undefined,
        schedule: schedulePayload,
      }
      await api.patch(`/alerts/rules/${editingRule.value.id}`, payload)
    } else {
      const payload = {
        condition: ruleForm.value.condition,
        min_duration_seconds: ruleForm.value.min_duration_seconds || 0,
        channel_ids: ruleForm.value.channel_ids,
        schedule: schedulePayload,
      }
      if (ruleForm.value.target_type === 'monitor') {
        payload.monitor_id = ruleForm.value.target_id
      } else {
        payload.group_id = ruleForm.value.target_id
      }
      if (ruleForm.value.threshold_value != null) payload.threshold_value = ruleForm.value.threshold_value
      if (ruleForm.value.renotify_after_minutes) payload.renotify_after_minutes = ruleForm.value.renotify_after_minutes
      if (ruleForm.value.digest_minutes) payload.digest_minutes = ruleForm.value.digest_minutes
      if (ruleForm.value.anomaly_zscore_threshold) payload.anomaly_zscore_threshold = ruleForm.value.anomaly_zscore_threshold
      if (ruleForm.value.baseline_factor) payload.baseline_factor = ruleForm.value.baseline_factor
      await api.post('/alerts/rules', payload)
    }
    closeRuleModal()
    await loadData()
    success(isEditing ? t('alerts.toast_rule_updated') : t('alerts.toast_rule_created'))
  } catch (err) {
    ruleError.value = err.response?.data?.detail || t('alerts.toast_error_saving_rule')
  } finally {
    ruleLoading.value = false
  }
}

onMounted(async () => {
  await loadData()
  try {
    const [mResp, gResp] = await Promise.all([monitorsApi.list(), groupsApi.list()])
    allMonitors.value = mResp.data
    allGroups.value = gResp.data
  } catch {}
  // Load threshold suggestions (non-blocking)
  loadSuggestions()
})
</script>
