<template>
  <BaseModal :title="t('monitors.add')" size="lg" @close="$emit('close')">
      <form @submit.prevent="handleSubmit" class="space-y-4">

        <!-- Check type selector -->
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-2">{{ t('create_monitor.check_type') }}</label>
          <div class="grid grid-cols-4 sm:grid-cols-6 gap-1">
            <button
              v-for="t in checkTypes" :key="t.value" type="button"
              @click="form.check_type = t.value"
              class="py-2 px-1 rounded-lg border text-xs font-medium transition-colors text-center"
              :class="form.check_type === t.value
                ? 'bg-blue-600 border-blue-500 text-white'
                : 'border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300'"
            >
              <div class="text-base mb-0.5">{{ t.icon }}</div>
              {{ t.label }}
            </button>
          </div>
          <p class="text-xs text-gray-500 mt-1.5">{{ currentType.description }}</p>
        </div>

        <!-- Name -->
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('common.name') }} *</label>
          <input v-model="form.name" class="input w-full" :placeholder="currentType.namePlaceholder" required />
        </div>

        <!-- URL / Host field -->
        <div v-if="form.check_type !== 'scenario' && form.check_type !== 'heartbeat' && form.check_type !== 'composite'">
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ currentType.urlLabel }} *</label>
          <input
            v-model="form.url"
            class="input w-full"
            :placeholder="currentType.urlPlaceholder"
            :type="['http', 'keyword', 'json_path'].includes(form.check_type) ? 'url' : 'text'"
            :required="form.check_type !== 'scenario' && form.check_type !== 'heartbeat'"
          />
        </div>

        <!-- Heartbeat options -->
        <template v-if="form.check_type === 'heartbeat'">
          <!-- Slug -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.heartbeat_slug') }} *</label>
            <input v-model="form.heartbeat_slug" class="input w-full" placeholder="mon-cron-backup"
              pattern="[a-z0-9\-]+" required />
            <p class="text-xs text-gray-500 mt-1">
              {{ t('create_monitor.heartbeat_slug_hint') }} <code class="font-mono text-blue-400">POST /api/v1/ping/{{ form.heartbeat_slug || 'your-slug' }}</code>
            </p>
          </div>
          <!-- Interval / Grace -->
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.heartbeat_interval') }} *</label>
              <input v-model.number="form.heartbeat_interval_seconds" type="number" min="60" class="input w-full"
                placeholder="86400 (1 day)" required />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('create_monitor.heartbeat_grace') }}</label>
              <input v-model.number="form.heartbeat_grace_seconds" type="number" min="30" class="input w-full"
                placeholder="300 (5 min)" />
            </div>
          </div>
        </template>

        <!-- TCP port -->
        <div v-if="form.check_type === 'tcp'">
          <label class="block text-sm font-medium text-gray-300 mb-1">Port *</label>
          <input v-model.number="form.tcp_port" class="input w-full" type="number" min="1" max="65535" placeholder="e.g. 443, 22, 5432" required />
        </div>

        <!-- UDP port -->
        <div v-if="form.check_type === 'udp'">
          <label class="block text-sm font-medium text-gray-300 mb-1">Port *</label>
          <input v-model.number="form.udp_port" class="input w-full" type="number" min="1" max="65535" placeholder="e.g. 53, 123, 161" required />
          <p class="text-xs text-gray-500 mt-1">Sends an empty datagram — no ICMP unreachable = port open/filtered → up.</p>
        </div>

        <!-- SMTP options -->
        <div v-if="form.check_type === 'smtp'" class="space-y-3">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-300 mb-1">Port</label>
              <input v-model.number="form.smtp_port" class="input w-full" type="number" min="1" max="65535" placeholder="25" />
            </div>
            <div class="flex items-end pb-1">
              <div class="flex items-center gap-2">
                <input v-model="form.smtp_starttls" type="checkbox" id="smtp_starttls" />
                <label for="smtp_starttls" class="text-sm text-gray-300">STARTTLS</label>
              </div>
            </div>
          </div>
        </div>

        <!-- Domain expiry options -->
        <div v-if="form.check_type === 'domain_expiry'">
          <label class="block text-sm font-medium text-gray-300 mb-1">Alert threshold (days)</label>
          <input v-model.number="form.domain_expiry_warn_days" class="input w-full" type="number" min="1" max="365" placeholder="30" />
          <p class="text-xs text-gray-500 mt-1">Alert when domain expires in ≤ N days.</p>
        </div>

        <!-- DNS options -->
        <div v-if="form.check_type === 'dns'" class="space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-300 mb-1">Record type</label>
              <select v-model="form.dns_record_type" class="input w-full">
                <option v-for="r in dnsRecordTypes" :key="r" :value="r">{{ r }}</option>
              </select>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-300 mb-1">Expected value <span class="text-gray-500">(optional)</span></label>
              <input v-model="form.dns_expected_value" class="input w-full" placeholder="1.2.3.4" />
            </div>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('monitors.dns_nameservers.label') }} <span class="text-gray-500">(optional)</span></label>
            <input v-model="form.dns_nameservers_raw" class="input w-full" :placeholder="t('monitors.dns_nameservers.placeholder')" />
            <p class="text-xs text-gray-500 mt-1">{{ t('monitors.dns_nameservers.desc') }}</p>
          </div>
          <div class="rounded-lg border border-gray-700 p-3 space-y-3">
            <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide">{{ t('monitors.dns_drift.label') }}</p>
            <div class="flex items-start gap-3">
              <input v-model="form.dns_drift_alert" type="checkbox" id="dns_drift_alert" class="mt-0.5" />
              <div>
                <label for="dns_drift_alert" class="text-sm text-gray-300">{{ t('monitors.dns_drift.label') }}</label>
                <p class="text-xs text-gray-500">{{ t('monitors.dns_drift.desc') }}</p>
              </div>
            </div>
            <div v-if="form.dns_drift_alert" class="flex items-start gap-3 pl-1">
              <input v-model="form.dns_split_enabled" type="checkbox" id="dns_split_enabled" class="mt-0.5" />
              <div>
                <label for="dns_split_enabled" class="text-sm text-gray-300">{{ t('monitors.dns_drift.split_horizon') }}</label>
                <p class="text-xs text-gray-500">{{ t('monitors.dns_drift.split_horizon_desc') }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- Composite options -->
        <div v-if="form.check_type === 'composite'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('monitors.composite.aggregation') }}</label>
            <select v-model="form.composite_aggregation" class="input w-full">
              <option value="majority_up">{{ t('monitors.composite.aggregation_majority_up') }}</option>
              <option value="all_up">{{ t('monitors.composite.aggregation_all_up') }}</option>
              <option value="any_up">{{ t('monitors.composite.aggregation_any_up') }}</option>
              <option value="weighted_up">{{ t('monitors.composite.aggregation_weighted_up') }}</option>
            </select>
            <p class="text-xs text-gray-500 mt-1">{{ t('monitors.composite.desc') }}</p>
          </div>
          <p class="text-xs text-gray-500 bg-gray-800/50 rounded p-2">
            Member monitors can be added after creation from the monitor detail page.
          </p>
        </div>

        <!-- Keyword options -->
        <div v-if="form.check_type === 'keyword'">
          <label class="block text-sm font-medium text-gray-300 mb-1">Keyword to find *</label>
          <input v-model="form.keyword" class="input w-full" placeholder="e.g. &quot;status&quot;: &quot;ok&quot;" required />
          <div class="flex items-center gap-2 mt-2">
            <input v-model="form.keyword_negate" type="checkbox" id="negate" />
            <label for="negate" class="text-sm text-gray-400">Alert if keyword <strong class="text-white">IS found</strong> (negate check)</label>
          </div>
        </div>

        <!-- JSON path options -->
        <div v-if="form.check_type === 'json_path'" class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">JSON path *</label>
            <input v-model="form.expected_json_path" class="input w-full" placeholder="$.status" required />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Expected value <span class="text-gray-500">(optional)</span></label>
            <input v-model="form.expected_json_value" class="input w-full" placeholder="ok" />
          </div>
        </div>

        <!-- Scenario builder -->
        <div v-if="form.check_type === 'scenario'">
          <label class="block text-sm font-medium text-gray-300 mb-2">{{ t('create_monitor.scenario_label') }}</label>
          <ScenarioBuilder
            v-model="form.scenario_steps"
            :variables="form.scenario_variables"
            @update:variables="form.scenario_variables = $event"
          />
        </div>

        <!-- Network scope (hidden for heartbeat and composite) -->
        <div v-if="form.check_type !== 'heartbeat' && form.check_type !== 'composite'">
          <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('monitors.network_scope.label') }}</label>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="s in networkScopes" :key="s.value" type="button"
              @click="form.network_scope = s.value"
              class="py-2 px-2 rounded-lg border text-xs font-medium transition-colors text-center"
              :class="form.network_scope === s.value
                ? 'bg-blue-600 border-blue-500 text-white'
                : 'border-gray-700 text-gray-400 hover:border-gray-600 hover:text-gray-300'"
            >
              <div class="text-base mb-0.5">{{ s.icon }}</div>
              {{ s.label }}
            </button>
          </div>
          <p class="text-xs text-gray-500 mt-1">{{ networkScopes.find(s => s.value === form.network_scope)?.desc }}</p>
        </div>

        <!-- Interval / Timeout (hidden for heartbeat and composite — no physical probe) -->
        <div v-if="form.check_type !== 'heartbeat' && form.check_type !== 'composite'" class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Interval (s)</label>
            <input v-model.number="form.interval_seconds" class="input w-full" type="number" min="5" max="86400" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Timeout (s)</label>
            <input v-model.number="form.timeout_seconds" class="input w-full" type="number" min="1" max="60" />
          </div>
        </div>

        <!-- HTTP-only options -->
        <template v-if="['http', 'keyword', 'json_path'].includes(form.check_type)">
          <div class="flex items-center gap-3">
            <input v-model="form.follow_redirects" type="checkbox" id="redirects" />
            <label for="redirects" class="text-sm text-gray-300">Follow redirects</label>
          </div>
          <div class="flex items-center gap-3">
            <input v-model="form.ssl_check_enabled" type="checkbox" id="ssl" />
            <label for="ssl" class="text-sm text-gray-300">Monitor SSL certificate</label>
          </div>

          <!-- Custom request headers accordion -->
          <div class="border border-gray-700 rounded-lg overflow-hidden">
            <button
              type="button"
              @click="showCustomHeaders = !showCustomHeaders"
              class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
            >
              <span>{{ t('monitors.customHeaders.title') }}</span>
              <span class="text-xs transition-transform" :class="showCustomHeaders ? 'rotate-180' : ''">▼</span>
            </button>
            <div v-if="showCustomHeaders" class="px-4 pb-4 pt-2 space-y-3 border-t border-gray-700 bg-gray-800/20">
              <p class="text-xs text-gray-500">{{ t('monitors.customHeaders.desc') }}</p>
              <div class="flex items-center gap-2">
                <label class="text-xs text-gray-400 shrink-0">{{ t('monitors.customHeaders.presets.label') }}</label>
                <select v-model="selectedUaPreset" @change="onUaPresetChange" class="input text-xs flex-1">
                  <option value="">{{ t('monitors.customHeaders.presets.choose') }}</option>
                  <option v-for="p in UA_PRESETS" :key="p.id" :value="p.id">{{ t(p.labelKey) }}</option>
                </select>
              </div>
              <div v-if="form.custom_headers_list.length" class="space-y-2">
                <div v-for="(h, idx) in form.custom_headers_list" :key="idx" class="flex gap-2 items-center">
                  <input v-model="h.key" class="input flex-1 font-mono text-xs" :placeholder="t('monitors.customHeaders.namePlaceholder')" maxlength="100" />
                  <input v-model="h.value" class="input flex-1 font-mono text-xs" :placeholder="t('monitors.customHeaders.valuePlaceholder')" maxlength="500" />
                  <button type="button" @click="removeCustomHeader(idx)" class="text-red-400 hover:text-red-300 text-xs px-1 shrink-0">✕</button>
                </div>
              </div>
              <p v-else class="text-xs text-gray-600">{{ t('monitors.customHeaders.empty') }}</p>
              <button
                type="button"
                @click="addCustomHeader"
                class="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                :disabled="form.custom_headers_list.length >= 20"
              >+ {{ t('monitors.customHeaders.add') }}</button>
            </div>
          </div>

          <!-- Advanced assertions accordion -->
          <div class="border border-gray-700 rounded-lg overflow-hidden">
            <button
              type="button"
              @click="showAdvanced = !showAdvanced"
              class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
            >
              <span>{{ t('create_monitor.advanced_assertions') }}</span>
              <span class="text-xs transition-transform" :class="showAdvanced ? 'rotate-180' : ''">▼</span>
            </button>
            <div v-if="showAdvanced" class="px-4 pb-4 pt-2 space-y-4 border-t border-gray-700 bg-gray-800/20">
              <!-- Regex body -->
              <div>
                <label class="block text-sm font-medium text-gray-300 mb-1">
                  {{ t('create_monitor.body_regex') }} <span class="text-gray-500">({{ t('common.optional') }})</span>
                </label>
                <input
                  v-model="form.body_regex"
                  class="input w-full font-mono text-sm"
                  placeholder='.*"status":"ok".*'
                />
                <p class="text-xs text-gray-500 mt-1">{{ t('create_monitor.body_regex_hint') }}</p>
              </div>

              <!-- Expected headers -->
              <div>
                <div class="flex items-center justify-between mb-2">
                  <label class="text-sm font-medium text-gray-300">{{ t('create_monitor.expected_headers') }}</label>
                  <button
                    type="button"
                    @click="addExpectedHeader"
                    class="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                  >+ {{ t('common.add') }}</button>
                </div>
                <div v-if="form.expected_headers_list.length" class="space-y-2">
                  <div v-for="(h, idx) in form.expected_headers_list" :key="idx" class="flex gap-2 items-center">
                    <input
                      v-model="h.key"
                      class="input flex-1 font-mono text-xs"
                      placeholder="content-type"
                    />
                    <input
                      v-model="h.value"
                      class="input flex-1 font-mono text-xs"
                      placeholder="application/json ou /pattern/"
                    />
                    <button
                      type="button"
                      @click="removeExpectedHeader(idx)"
                      class="text-red-400 hover:text-red-300 text-xs px-1 shrink-0"
                    >✕</button>
                  </div>
                </div>
                <p v-else class="text-xs text-gray-600">{{ t('create_monitor.no_headers') }}</p>
                <p class="text-xs text-gray-500 mt-1">{{ t('create_monitor.headers_regex_hint') }}</p>
              </div>

              <!-- JSON Schema -->
              <div>
                <label class="block text-sm font-medium text-gray-300 mb-1">
                  JSON Schema <span class="text-gray-500">({{ t('common.optional') }})</span>
                </label>
                <textarea
                  v-model="form.json_schema_text"
                  class="input w-full font-mono text-xs"
                  rows="4"
                  placeholder='{"type":"object","required":["status"],"properties":{"status":{"type":"string"}}}'
                ></textarea>
                <p v-if="jsonSchemaError" class="text-xs text-red-400 mt-1">{{ jsonSchemaError }}</p>
                <p class="text-xs text-gray-500 mt-1">{{ t('create_monitor.json_schema_hint') }}</p>
              </div>
            </div>
          </div>
        </template>

        <!-- Flapping detection overrides -->
        <div v-if="form.check_type !== 'heartbeat'" class="border border-gray-700 rounded-lg overflow-hidden">
          <button
            type="button"
            @click="showFlapping = !showFlapping"
            class="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-gray-800/50 transition-colors"
          >
            <span>{{ t('monitors.flapping_settings') }}</span>
            <span class="text-xs transition-transform" :class="showFlapping ? 'rotate-180' : ''">▼</span>
          </button>
          <div v-if="showFlapping" class="px-4 pb-4 pt-2 space-y-3 border-t border-gray-700 bg-gray-800/20">
            <p class="text-xs text-gray-500">{{ t('monitors.flapping_desc') }}</p>
            <div class="grid grid-cols-2 gap-4">
              <div>
                <label class="block text-xs text-gray-400 mb-1">{{ t('monitors.flap_threshold') }}</label>
                <input v-model.number="form.flap_threshold" type="number" min="2" max="50" class="input w-full" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">{{ t('monitors.flap_window_minutes') }}</label>
                <input v-model.number="form.flap_window_minutes" type="number" min="1" max="60" class="input w-full" />
              </div>
            </div>
            <div class="mt-3">
              <label class="block text-xs text-gray-400 mb-1">{{ t('monitors.auto_pause_after') }}</label>
              <input v-model.number="form.auto_pause_after" type="number" min="2" max="100" placeholder="" class="input w-full" />
              <p class="text-xs text-gray-500 mt-1">{{ t('monitors.auto_pause_after_hint') }}</p>
            </div>
          </div>
        </div>

        <!-- Alert setup -->
        <div class="border border-gray-800 rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-medium text-white">{{ t('monitors.alert_setup.title') }}</h3>
              <p class="text-xs text-gray-500 mt-0.5">{{ t('monitors.alert_setup.desc') }}</p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" v-model="alertEnabled" class="sr-only peer" />
              <div class="w-9 h-5 bg-gray-700 peer-checked:bg-blue-600 rounded-full
                after:content-[''] after:absolute after:top-0.5 after:left-[2px]
                after:bg-white after:rounded-full after:h-4 after:w-4
                after:transition-all peer-checked:after:translate-x-full"></div>
            </label>
          </div>
          <div v-if="alertEnabled">
            <div v-if="alertChannels.length === 0" class="text-xs text-amber-400 bg-amber-900/20 border border-amber-800/40 rounded-lg px-3 py-2">
              {{ t('monitors.alert_setup.no_channels') }}
            </div>
            <div v-else class="space-y-1.5">
              <label
                v-for="ch in alertChannels" :key="ch.id"
                class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
                :class="selectedChannelIds.includes(ch.id)
                  ? 'border-blue-600/60 bg-blue-950/30'
                  : 'border-gray-800 hover:border-gray-700'"
              >
                <input
                  type="checkbox"
                  :value="ch.id"
                  v-model="selectedChannelIds"
                  class="rounded bg-gray-800 border-gray-600 text-blue-500 focus:ring-blue-500/30"
                />
                <span class="text-sm text-gray-300">{{ ch.name }}</span>
                <span class="text-xs text-gray-600 ml-auto">{{ ch.type }}</span>
              </label>
            </div>
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')"
            class="btn-secondary flex-1">
            {{ t('common.cancel') }}
          </button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? t('common.loading') : t('monitors.add') }}
          </button>
        </div>
      </form>
  </BaseModal>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../../stores/monitors'
import api from '../../api/client'
import ScenarioBuilder from './ScenarioBuilder.vue'
import BaseModal from '../BaseModal.vue'
import { UA_PRESETS, applyUaPreset } from '../../lib/uaPresets'

const { t } = useI18n()

const props = defineProps({
  initialData: { type: Object, default: null },
})

const emit = defineEmits(['close', 'created'])
const monitorStore = useMonitorStore()

const showAdvanced = ref(false)
const showFlapping = ref(false)
const showCustomHeaders = ref(false)

const checkTypes = [
  {
    value: 'http',
    label: 'HTTP',
    icon: '🌐',
    description: 'Check that a URL returns an expected HTTP status code.',
    urlLabel: 'URL',
    urlPlaceholder: 'https://example.com',
    namePlaceholder: 'My Website',
  },
  {
    value: 'keyword',
    label: 'Keyword',
    icon: '🔍',
    description: 'HTTP check + verify a keyword is (or isn\'t) present in the response body.',
    urlLabel: 'URL',
    urlPlaceholder: 'https://api.example.com/health',
    namePlaceholder: 'API Health Check',
  },
  {
    value: 'json_path',
    label: 'JSON',
    icon: '{ }',
    description: 'HTTP check + validate a JSON path value in the response (e.g. $.status == "ok").',
    urlLabel: 'URL',
    urlPlaceholder: 'https://api.example.com/status',
    namePlaceholder: 'API Status',
  },
  {
    value: 'tcp',
    label: 'TCP',
    icon: '🔌',
    description: 'Check that a TCP port is reachable (databases, SSH, SMTP, etc.).',
    urlLabel: 'Host',
    urlPlaceholder: 'db.example.com',
    namePlaceholder: 'PostgreSQL DB',
  },
  {
    value: 'dns',
    label: 'DNS',
    icon: '📡',
    description: 'Check DNS resolution and optionally assert the returned value.',
    urlLabel: 'Domain',
    urlPlaceholder: 'example.com',
    namePlaceholder: 'DNS example.com',
  },
  {
    value: 'scenario',
    label: 'Scenario',
    icon: '🎭',
    description: 'Run a full browser scenario (authentication, clicks, assertions…).',
    urlLabel: 'Start URL',
    urlPlaceholder: 'https://app.example.com',
    namePlaceholder: 'Login + Dashboard',
  },
  {
    value: 'heartbeat',
    label: 'Heartbeat',
    icon: '⏰',
    description: "Dead man's switch for cron jobs: opens an incident if the ping doesn't come back within the interval + grace period.",
    urlLabel: '',
    urlPlaceholder: '',
    namePlaceholder: 'Daily Backup',
  },
  {
    value: 'udp',
    label: 'UDP',
    icon: '📦',
    description: 'Check that a UDP port is reachable (DNS, NTP, SNMP, game servers…).',
    urlLabel: 'Host',
    urlPlaceholder: 'dns.example.com',
    namePlaceholder: 'DNS UDP 53',
  },
  {
    value: 'smtp',
    label: 'SMTP',
    icon: '✉️',
    description: 'Connect to an SMTP server, verify the banner and EHLO response.',
    urlLabel: 'Mail server',
    urlPlaceholder: 'mail.example.com',
    namePlaceholder: 'SMTP Mail Server',
  },
  {
    value: 'ping',
    label: 'Ping',
    icon: '🏓',
    description: 'ICMP ping check — measures round-trip time and reachability.',
    urlLabel: 'Host',
    urlPlaceholder: 'router.internal',
    namePlaceholder: 'Gateway Ping',
  },
  {
    value: 'domain_expiry',
    label: 'Domain',
    icon: '🔑',
    description: 'Monitor domain expiry via WHOIS — alerts before your domain expires.',
    urlLabel: 'Domain',
    urlPlaceholder: 'example.com',
    namePlaceholder: 'example.com expiry',
  },
  {
    value: 'composite',
    label: 'Composite',
    icon: '🔗',
    description: 'Aggregate the state of multiple monitors into a single status (e.g. internal probe + external probe).',
    urlLabel: '',
    urlPlaceholder: '',
    namePlaceholder: 'My Service (aggregated)',
  },
]

const dnsRecordTypes = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS']

const networkScopes = [
  { value: 'all', icon: '🌍', label: t('monitors.network_scope.all'), desc: t('monitors.network_scope.all_desc') },
  { value: 'internal', icon: '🏠', label: t('monitors.network_scope.internal'), desc: t('monitors.network_scope.internal_desc') },
  { value: 'external', icon: '☁️', label: t('monitors.network_scope.external'), desc: t('monitors.network_scope.external_desc') },
]

const currentType = computed(() => checkTypes.find(t => t.value === form.value.check_type) || checkTypes[0])

const form = ref({
  name: '',
  url: '',
  check_type: 'http',
  interval_seconds: 60,
  timeout_seconds: 10,
  follow_redirects: true,
  ssl_check_enabled: true,
  expected_status_codes: [200],
  tcp_port: null,
  udp_port: null,
  smtp_port: null,
  smtp_starttls: false,
  domain_expiry_warn_days: 30,
  dns_record_type: 'A',
  dns_expected_value: '',
  dns_nameservers_raw: '',
  keyword: '',
  keyword_negate: false,
  expected_json_path: '',
  expected_json_value: '',
  scenario_steps: [],
  scenario_variables: [],
  heartbeat_slug: '',
  heartbeat_interval_seconds: null,
  heartbeat_grace_seconds: 300,
  // Advanced assertions
  body_regex: '',
  expected_headers_list: [],  // [{key, value}]
  custom_headers_list: [],    // [{key, value}] — request headers (UA override, auth)
  json_schema_text: '',
  // Flapping
  flap_threshold: 5,
  flap_window_minutes: 10,
  auto_pause_after: null,
  // DNS drift
  dns_drift_alert: false,
  dns_split_enabled: false,
  // Network scope
  network_scope: 'all',
  // Composite
  composite_aggregation: 'majority_up',
})

// Pre-fill form when cloning (initialData prop)
onMounted(() => {
  if (props.initialData) {
    const data = { ...props.initialData }
    // Convert expected_headers object to list format used by the form
    if (data.expected_headers && typeof data.expected_headers === 'object') {
      data.expected_headers_list = Object.entries(data.expected_headers).map(([key, value]) => ({ key, value }))
      delete data.expected_headers
    }
    if (data.custom_headers && typeof data.custom_headers === 'object') {
      data.custom_headers_list = Object.entries(data.custom_headers).map(([key, value]) => ({ key, value }))
      delete data.custom_headers
    }
    // Convert json_schema object to text format used by the form
    if (data.json_schema) {
      data.json_schema_text = JSON.stringify(data.json_schema, null, 2)
      delete data.json_schema
    }
    Object.assign(form.value, data)
  }
})

// Alert channels for auto-alert setup
const alertChannels = ref([])
const alertEnabled = ref(true)
const selectedChannelIds = ref([])

async function loadAlertChannels() {
  try {
    const { data } = await api.get('/alerts/channels')
    alertChannels.value = data
    // Pre-select all channels
    selectedChannelIds.value = data.map(c => c.id)
  } catch {}
}
loadAlertChannels()

const loading = ref(false)
const error = ref('')
const jsonSchemaError = ref('')

function addExpectedHeader() {
  form.value.expected_headers_list.push({ key: '', value: '' })
}

function removeExpectedHeader(idx) {
  form.value.expected_headers_list.splice(idx, 1)
}

function addCustomHeader() {
  if (form.value.custom_headers_list.length >= 20) return
  form.value.custom_headers_list.push({ key: '', value: '' })
}

function removeCustomHeader(idx) {
  form.value.custom_headers_list.splice(idx, 1)
}

const selectedUaPreset = ref('')
function onUaPresetChange() {
  const preset = UA_PRESETS.find(p => p.id === selectedUaPreset.value)
  if (!preset) return
  const next = applyUaPreset(form.value.custom_headers_list, preset.value)
  if (next.length > 20) return
  form.value.custom_headers_list = next
  selectedUaPreset.value = ''
}

function buildPayload() {
  const p = {
    name: form.value.name,
    check_type: form.value.check_type,
    interval_seconds: form.value.interval_seconds,
    timeout_seconds: form.value.timeout_seconds,
    expected_status_codes: form.value.expected_status_codes,
  }

  // Normalize URL: non-HTTP types may receive bare hostnames — wrap in http:// for server schema
  const bareHostTypes = ['tcp', 'udp', 'dns', 'smtp', 'ping', 'domain_expiry']
  let url = form.value.url.trim()
  if (bareHostTypes.includes(form.value.check_type)) {
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'http://' + url
    }
  }
  p.url = url

  if (['http', 'keyword', 'json_path'].includes(form.value.check_type)) {
    p.follow_redirects = form.value.follow_redirects
    p.ssl_check_enabled = form.value.ssl_check_enabled
  }

  if (form.value.check_type === 'tcp') {
    p.tcp_port = form.value.tcp_port
  }

  if (form.value.check_type === 'udp') {
    p.udp_port = form.value.udp_port
  }

  if (form.value.check_type === 'smtp') {
    if (form.value.smtp_port) p.smtp_port = form.value.smtp_port
    p.smtp_starttls = form.value.smtp_starttls
  }

  if (form.value.check_type === 'domain_expiry') {
    p.domain_expiry_warn_days = form.value.domain_expiry_warn_days
  }

  if (form.value.check_type === 'dns') {
    p.dns_record_type = form.value.dns_record_type
    if (form.value.dns_expected_value) p.dns_expected_value = form.value.dns_expected_value
    const ns = form.value.dns_nameservers_raw?.split(',').map(s => s.trim()).filter(Boolean)
    if (ns?.length) p.dns_nameservers = ns
    p.dns_drift_alert = form.value.dns_drift_alert
    p.dns_split_enabled = form.value.dns_split_enabled
  }

  // Network scope (applies to all non-heartbeat, non-composite)
  if (form.value.check_type !== 'heartbeat' && form.value.check_type !== 'composite') {
    p.network_scope = form.value.network_scope
  }

  if (form.value.check_type === 'composite') {
    p.url = 'http://composite'
    p.composite_aggregation = form.value.composite_aggregation
  }

  if (form.value.check_type === 'keyword') {
    p.keyword = form.value.keyword
    p.keyword_negate = form.value.keyword_negate
  }

  if (form.value.check_type === 'json_path') {
    p.expected_json_path = form.value.expected_json_path
    if (form.value.expected_json_value) p.expected_json_value = form.value.expected_json_value
  }

  if (form.value.check_type === 'scenario') {
    p.scenario_steps = form.value.scenario_steps
    p.scenario_variables = form.value.scenario_variables
    // url is optional for scenario (use first navigate step's url if empty)
    if (!p.url) p.url = 'http://scenario'
  }

  if (form.value.check_type === 'heartbeat') {
    p.url = 'http://heartbeat'
    p.heartbeat_slug = form.value.heartbeat_slug
    p.heartbeat_interval_seconds = form.value.heartbeat_interval_seconds
    p.heartbeat_grace_seconds = form.value.heartbeat_grace_seconds
  }

  // Advanced HTTP assertions (http / keyword / json_path)
  if (['http', 'keyword', 'json_path'].includes(form.value.check_type)) {
    if (form.value.body_regex) {
      p.body_regex = form.value.body_regex
    }
    const validHeaders = form.value.expected_headers_list.filter(h => h.key.trim())
    if (validHeaders.length) {
      p.expected_headers = Object.fromEntries(validHeaders.map(h => [h.key.trim(), h.value]))
    }
    if (form.value.json_schema_text.trim()) {
      try {
        p.json_schema = JSON.parse(form.value.json_schema_text)
        jsonSchemaError.value = ''
      } catch (e) {
        jsonSchemaError.value = 'JSON Schema invalide : ' + e.message
        throw new Error('JSON Schema invalide')
      }
    }
    const validCustom = form.value.custom_headers_list.filter(h => h.key.trim() && h.value.trim())
    if (validCustom.length) {
      p.custom_headers = Object.fromEntries(validCustom.map(h => [h.key.trim(), h.value]))
    }
  }

  // Flapping overrides
  if (form.value.check_type !== 'heartbeat') {
    p.flap_threshold = form.value.flap_threshold
    p.flap_window_minutes = form.value.flap_window_minutes
  }

  // Auto-pause after N consecutive failures
  if (form.value.auto_pause_after) {
    p.auto_pause_after = form.value.auto_pause_after
  }

  // Auto-alert: pass selected channel IDs for automatic rule creation
  if (alertEnabled.value && selectedChannelIds.value.length > 0) {
    p.alert_channel_ids = selectedChannelIds.value
  }

  return p
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    await monitorStore.create(buildPayload())
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create monitor'
  } finally {
    loading.value = false
  }
}
</script>
