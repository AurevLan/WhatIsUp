<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-semibold text-white">Add Alert Channel</h2>
        <button @click="$emit('close')" class="text-gray-400 hover:text-white">✕</button>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Name *</label>
          <input v-model="form.name" class="input w-full" placeholder="My Email Channel" required />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Type *</label>
          <select v-model="form.type" class="input w-full" required>
            <option value="">Select type...</option>
            <option value="email">📧 Email</option>
            <option value="webhook">🔗 Webhook</option>
            <option value="telegram">✈️ Telegram</option>
            <option value="slack">💬 Slack</option>
            <option value="pagerduty">🔔 PagerDuty</option>
            <option value="opsgenie">🚨 Opsgenie</option>
          </select>
        </div>

        <!-- Email config -->
        <div v-if="form.type === 'email'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Recipients (comma-separated) *</label>
            <input v-model="emailTo" class="input w-full" placeholder="alert@example.com, ops@example.com" required />
          </div>
        </div>

        <!-- Webhook config -->
        <div v-if="form.type === 'webhook'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">URL *</label>
            <input v-model="webhookUrl" class="input w-full" placeholder="https://hooks.slack.com/..." type="url" required />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Secret (for HMAC signature)</label>
            <input v-model="webhookSecret" class="input w-full" placeholder="Optional secret" />
          </div>
        </div>

        <!-- Slack config -->
        <div v-if="form.type === 'slack'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
            <input v-model="slackWebhookUrl" class="input w-full" placeholder="https://hooks.slack.com/services/..." type="url" required />
            <p class="text-xs text-gray-500 mt-1">Create an Incoming Webhook in your Slack workspace.</p>
          </div>
        </div>

        <!-- Telegram config -->
        <div v-if="form.type === 'telegram'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Bot Token *</label>
            <input v-model="telegramToken" class="input w-full" placeholder="1234567890:ABC..." required />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Chat ID *</label>
            <input v-model="telegramChatId" class="input w-full" placeholder="-1001234567890" required />
          </div>
        </div>

        <!-- PagerDuty config -->
        <div v-if="form.type === 'pagerduty'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Integration Key (Routing Key) *</label>
            <input v-model="pdIntegrationKey" class="input w-full" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" required />
            <p class="text-xs text-gray-500 mt-1">Find this key in your PagerDuty service (Events API v2).</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Severity</label>
            <select v-model="pdSeverity" class="input w-full">
              <option value="critical">critical</option>
              <option value="error">error</option>
              <option value="warning">warning</option>
              <option value="info">info</option>
            </select>
          </div>
        </div>

        <!-- Opsgenie config -->
        <div v-if="form.type === 'opsgenie'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">API Key *</label>
            <input v-model="opsApiKey" class="input w-full" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required />
            <p class="text-xs text-gray-500 mt-1">Opsgenie API key (team settings).</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Region</label>
            <select v-model="opsRegion" class="input w-full">
              <option value="us">US (api.opsgenie.com)</option>
              <option value="eu">EU (api.eu.opsgenie.com)</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Priority</label>
            <select v-model="opsPriority" class="input w-full">
              <option value="P1">P1 — Critical</option>
              <option value="P2">P2 — High</option>
              <option value="P3">P3 — Medium</option>
              <option value="P4">P4 — Low</option>
              <option value="P5">P5 — Info</option>
            </select>
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">Cancel</button>
          <button type="submit" :disabled="loading || !form.type" class="flex-1 btn-primary">
            {{ loading ? 'Adding…' : 'Add channel' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '../../api/client'

const emit = defineEmits(['close', 'created'])
const form = ref({ name: '', type: '' })
const loading = ref(false)
const error = ref('')

const emailTo = ref('')
const webhookUrl = ref('')
const webhookSecret = ref('')
const telegramToken = ref('')
const telegramChatId = ref('')
const slackWebhookUrl = ref('')
const pdIntegrationKey = ref('')
const pdSeverity = ref('critical')
const opsApiKey = ref('')
const opsRegion = ref('us')
const opsPriority = ref('P1')

function buildConfig() {
  switch (form.value.type) {
    case 'email':
      return { to: emailTo.value.split(',').map(e => e.trim()).filter(Boolean) }
    case 'webhook':
      return { url: webhookUrl.value, secret: webhookSecret.value || undefined }
    case 'telegram':
      return { bot_token: telegramToken.value, chat_id: telegramChatId.value }
    case 'slack':
      return { webhook_url: slackWebhookUrl.value }
    case 'pagerduty':
      return { integration_key: pdIntegrationKey.value, severity: pdSeverity.value }
    case 'opsgenie':
      return { api_key: opsApiKey.value, region: opsRegion.value, priority: opsPriority.value }
    default:
      return {}
  }
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    await api.post('/alerts/channels', { ...form.value, config: buildConfig() })
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to add channel'
  } finally {
    loading.value = false
  }
}
</script>
