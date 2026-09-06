<template>
  <BaseModal :title="t('monitors.add')" size="lg" @close="$emit('close')">
      <form @submit.prevent="handleSubmit" class="space-y-4">

        <MonitorFormFields mode="create" :json-schema-error="jsonSchemaError" />


        <!-- Alert setup -->
        <div class="border border-(--border) rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-medium text-(--text-1)">{{ t('monitors.alert_setup.title') }}</h3>
              <p class="text-xs text-(--text-3) mt-0.5">{{ t('monitors.alert_setup.desc') }}</p>
            </div>
            <label class="relative inline-flex items-center cursor-pointer">
              <input type="checkbox" v-model="alertEnabled" class="sr-only peer" />
              <div class="w-9 h-5 bg-(--bg-surface-2) peer-checked:bg-(--accent) rounded-full
                after:content-[''] after:absolute after:top-0.5 after:left-[2px]
                after:bg-white after:rounded-full after:h-4 after:w-4
                after:transition-all peer-checked:after:translate-x-full"></div>
            </label>
          </div>
          <div v-if="alertEnabled">
            <div v-if="alertChannels.length === 0" class="text-xs text-(--warn) bg-[color-mix(in_srgb,var(--warn)_10%,transparent)] border border-[color-mix(in_srgb,var(--warn)_25%,transparent)] rounded-lg px-3 py-2">
              {{ t('monitors.alert_setup.no_channels') }}
            </div>
            <div v-else class="space-y-1.5">
              <label
                v-for="ch in alertChannels" :key="ch.id"
                class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
                :class="selectedChannelIds.includes(ch.id)
                  ? 'border-(--accent-border) bg-(--accent-glow)'
                  : 'border-(--border) hover:border-(--border-hover)'"
              >
                <input
                  type="checkbox"
                  :value="ch.id"
                  v-model="selectedChannelIds"
                  class="rounded bg-(--bg-surface-2) border-(--border) text-(--accent) focus:ring-(--accent-border)"
                />
                <span class="text-sm text-(--text-2)">{{ ch.name }}</span>
                <span class="text-xs text-(--text-3) ml-auto">{{ ch.type }}</span>
              </label>
            </div>
          </div>
        </div>

        <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_12%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
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
import { ref, onMounted, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../../stores/monitors'
import api from '../../api/client'
import BaseModal from '../BaseModal.vue'
import MonitorFormFields from './MonitorFormFields.vue'
import { MonitorFormKey } from './monitorFormKeys'

const { t } = useI18n()

const props = defineProps({
  initialData: { type: Object, default: null },
  initialType: { type: String, default: null },
})

const emit = defineEmits(['close', 'created'])
const monitorStore = useMonitorStore()

const form = ref({
  name: '',
  url: '',
  check_type: 'http',
  interval_seconds: 60,
  timeout_seconds: 10,
  follow_redirects: true,
  ssl_check_enabled: true,
  ssl_pin_sha256: '',
  ssl_min_chain_days: null,
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
  auto_pause_after: null,
  // DNS drift
  dns_drift_alert: false,
  dns_split_enabled: false,
  // Network scope
  network_scope: 'all',
  // Composite
  composite_aggregation: 'majority_up',
})

// Les champs partagés (MonitorFormFields) mutent ce formulaire via v-model.
// Le ref est fourni tel quel : il n'est jamais réassigné (Object.assign
// ci-dessous), donc le lien reste valide.
provide(MonitorFormKey, form)

// Pre-fill form when cloning (initialData prop)
onMounted(() => {
  // Pre-select a check type (handoff from the wizard) — initialData still wins below.
  if (props.initialType) {
    form.value.check_type = props.initialType
  }
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
    p.ssl_pin_sha256 = form.value.ssl_pin_sha256?.trim() || null
    p.ssl_min_chain_days = form.value.ssl_min_chain_days || null
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
        throw new Error('JSON Schema invalide', { cause: e })
      }
    }
    const validCustom = form.value.custom_headers_list.filter(h => h.key.trim() && h.value.trim())
    if (validCustom.length) {
      p.custom_headers = Object.fromEntries(validCustom.map(h => [h.key.trim(), h.value]))
    }
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
    await monitorStore.create(buildPayload(), { skipErrorToast: true })
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create monitor'
  } finally {
    loading.value = false
  }
}
</script>
