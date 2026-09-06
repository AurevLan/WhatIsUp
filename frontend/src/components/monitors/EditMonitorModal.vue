<template>
  <BaseModal :title="t('monitors.edit_title')" size="lg" @close="$emit('close')">
      <form @submit.prevent="handleSubmit" class="space-y-4">

        <MonitorFormFields mode="edit" :json-schema-error="jsonSchemaError">
          <template #before-advanced-detection>
          <!-- Runbook -->
          <div class="border border-(--border) rounded-lg overflow-hidden">
            <div class="flex items-center justify-between px-4 py-2.5 bg-(--bg-surface-2)">
              <div class="flex items-start gap-3">
                <input v-model="form.runbook_enabled" type="checkbox" id="runbook_enabled" class="mt-0.5" />
                <label for="runbook_enabled" class="text-sm font-medium text-(--text-2) cursor-pointer">
                  {{ t('runbook.enable_label') }}
                  <p class="text-xs text-(--text-3) font-normal mt-0.5">{{ t('runbook.enable_desc') }}</p>
                </label>
              </div>
            </div>
            <div v-if="form.runbook_enabled" class="px-4 pb-4 pt-3 border-t border-(--border)">
              <textarea
                v-model="form.runbook_markdown"
                rows="8"
                maxlength="20000"
                class="input w-full font-mono text-sm"
                :placeholder="t('runbook.placeholder')"
              ></textarea>
              <p class="text-xs text-(--text-3) mt-1">{{ t('runbook.markdown_hint') }}</p>
            </div>
          </div>
          </template>
        </MonitorFormFields>

        <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_12%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1 justify-center">
            {{ t('common.cancel') }}
          </button>
          <button type="submit" :disabled="loading" class="btn-primary flex-1 justify-center">
            {{ loading ? t('common.loading') : t('common.save') }}
          </button>
        </div>
      </form>
  </BaseModal>
</template>

<script setup>
import { ref, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMonitorStore } from '../../stores/monitors'
import BaseModal from '../BaseModal.vue'
import MonitorFormFields from './MonitorFormFields.vue'
import { MonitorFormKey } from './monitorFormKeys'

const props = defineProps({
  monitor: { type: Object, required: true },
})

const { t } = useI18n()

const emit = defineEmits(['close', 'updated'])
const monitorStore = useMonitorStore()

// Strip http:// prefix added by buildPayload for bare-host types so the field looks clean
function stripScheme(url) {
  if (!url) return ''
  return url.replace(/^https?:\/\//, '')
}

const m = props.monitor
const bareHostTypes = ['tcp', 'udp', 'dns', 'smtp', 'ping', 'domain_expiry']

// Convert expected_headers object back to list for editing
const headersFromMonitor = m.expected_headers
  ? Object.entries(m.expected_headers).map(([key, value]) => ({ key, value }))
  : []

const customHeadersFromMonitor = m.custom_headers
  ? Object.entries(m.custom_headers).map(([key, value]) => ({ key, value }))
  : []

const form = ref({
  name: m.name || '',
  url: bareHostTypes.includes(m.check_type) ? stripScheme(m.url) : (m.url || ''),
  check_type: m.check_type || 'http',
  interval_seconds: m.interval_seconds ?? 60,
  timeout_seconds: m.timeout_seconds ?? 10,
  follow_redirects: m.follow_redirects ?? true,
  ssl_check_enabled: m.ssl_check_enabled ?? true,
  ssl_pin_sha256: m.ssl_pin_sha256 ?? '',
  ssl_min_chain_days: m.ssl_min_chain_days ?? null,
  expected_status_codes: m.expected_status_codes || [200],
  tcp_port: m.tcp_port ?? null,
  udp_port: m.udp_port ?? null,
  smtp_port: m.smtp_port ?? null,
  smtp_starttls: m.smtp_starttls ?? false,
  domain_expiry_warn_days: m.domain_expiry_warn_days ?? 30,
  dns_record_type: m.dns_record_type || 'A',
  dns_expected_value: m.dns_expected_value || '',
  dns_nameservers_raw: (m.dns_nameservers || []).join(', '),
  keyword: m.keyword || '',
  keyword_negate: m.keyword_negate ?? false,
  expected_json_path: m.expected_json_path || '',
  expected_json_value: m.expected_json_value || '',
  scenario_steps: m.scenario_steps || [],
  scenario_variables: m.scenario_variables || [],
  heartbeat_slug: m.heartbeat_slug || '',
  heartbeat_token: m.heartbeat_token || '',
  heartbeat_interval_seconds: m.heartbeat_interval_seconds ?? null,
  heartbeat_grace_seconds: m.heartbeat_grace_seconds ?? 300,
  body_regex: m.body_regex || '',
  expected_headers_list: headersFromMonitor,
  custom_headers_list: customHeadersFromMonitor,
  json_schema_text: m.json_schema ? JSON.stringify(m.json_schema, null, 2) : '',
  auto_pause_after: m.auto_pause_after ?? null,
  dns_drift_alert: m.dns_drift_alert ?? false,
  dns_split_enabled: m.dns_split_enabled ?? false,
  network_scope: m.network_scope || 'all',
  composite_aggregation: m.composite_aggregation || 'majority_up',
  runbook_enabled: m.runbook_enabled ?? false,
  runbook_markdown: m.runbook_markdown || '',
})

// Les champs partagés (MonitorFormFields) mutent ce formulaire via v-model ;
// ils ouvrent aussi d'eux-mêmes les accordéons déjà renseignés.
provide(MonitorFormKey, form)

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
    else p.dns_nameservers = null
    p.dns_drift_alert = form.value.dns_drift_alert
    p.dns_split_enabled = form.value.dns_split_enabled
  }

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
    if (!p.url) p.url = 'http://scenario'
  }

  if (form.value.check_type === 'heartbeat') {
    p.url = 'http://heartbeat'
    p.heartbeat_slug = form.value.heartbeat_slug
    p.heartbeat_interval_seconds = form.value.heartbeat_interval_seconds
    p.heartbeat_grace_seconds = form.value.heartbeat_grace_seconds
  }

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
    p.custom_headers = validCustom.length
      ? Object.fromEntries(validCustom.map(h => [h.key.trim(), h.value]))
      : null
  }

  // Auto-pause after N consecutive failures
  p.auto_pause_after = form.value.auto_pause_after || null

  // Runbook — option B: disabling wipes markdown server-side (deps.py monitor update)
  p.runbook_enabled = form.value.runbook_enabled
  if (form.value.runbook_enabled) {
    p.runbook_markdown = form.value.runbook_markdown || null
  } else {
    p.runbook_markdown = null
  }

  return p
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    await monitorStore.update(props.monitor.id, buildPayload(), { skipErrorToast: true })
    emit('updated')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to update monitor'
  } finally {
    loading.value = false
  }
}
</script>
