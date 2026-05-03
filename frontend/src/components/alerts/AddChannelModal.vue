<template>
  <BaseModal title="Add Alert Channel" @close="$emit('close')">

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
            <option value="signal">📱 Signal</option>
            <option value="discord">🎮 Discord</option>
            <option value="mattermost">💬 Mattermost</option>
            <option value="teams">👥 Microsoft Teams</option>
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
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">{{ t('alerts.webhook_template') }}</label>
            <textarea
              v-model="webhookTemplate"
              class="input w-full font-mono text-xs"
              rows="5"
              :placeholder="t('alerts.webhook_template_placeholder')"
            ></textarea>
            <p class="text-xs text-gray-500 mt-1">{{ t('alerts.webhook_template_hint') }}</p>
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

        <!-- Discord config -->
        <div v-if="form.type === 'discord'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
            <input v-model="discordWebhookUrl" class="input w-full" placeholder="https://discord.com/api/webhooks/..." type="url" required />
            <p class="text-xs text-gray-500 mt-1">Server Settings → Integrations → Webhooks → New Webhook.</p>
          </div>
        </div>

        <!-- Mattermost config -->
        <div v-if="form.type === 'mattermost'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
            <input v-model="mattermostWebhookUrl" class="input w-full" placeholder="https://mattermost.example.com/hooks/..." type="url" required />
            <p class="text-xs text-gray-500 mt-1">System Console → Integrations → Incoming Webhooks.</p>
          </div>
        </div>

        <!-- Teams config -->
        <div v-if="form.type === 'teams'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
            <input v-model="teamsWebhookUrl" class="input w-full" placeholder="https://prod-XX.westus.logic.azure.com/..." type="url" required />
            <p class="text-xs text-gray-500 mt-1">Power Automate workflow with HTTP trigger → "Post adaptive card in a chat or channel". Legacy Office 365 connectors also work.</p>
          </div>
        </div>

        <!-- Telegram config -->
        <div v-if="form.type === 'telegram'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Bot Token *</label>
            <div class="flex gap-2">
              <input v-model="telegramToken" class="input flex-1" placeholder="1234567890:ABC..." required />
              <button
                type="button"
                @click="resolveTelegram"
                :disabled="!telegramToken || telegramResolving"
                class="px-3 py-2 text-sm bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg whitespace-nowrap"
              >
                {{ telegramResolving ? '…' : 'Fetch chat ID' }}
              </button>
            </div>
            <p class="text-xs text-gray-500 mt-1">Send any message to your bot first, then click "Fetch chat ID".</p>
          </div>
          <div v-if="telegramChatName" class="flex items-center gap-2 bg-green-900/30 border border-green-700/50 rounded-lg px-3 py-2 text-sm text-green-300">
            <span>✅</span>
            <span>Connected to <strong>{{ telegramChatName }}</strong> (ID: {{ telegramChatId }})</span>
          </div>
          <div v-if="telegramResolveError" class="bg-red-900/40 border border-red-700 rounded-lg px-3 py-2 text-sm text-red-300">
            {{ telegramResolveError }}
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Chat ID *</label>
            <input v-model="telegramChatId" class="input w-full" placeholder="Auto-filled after fetch" required />
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

        <!-- Signal config -->
        <div v-if="form.type === 'signal'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Signal REST API URL *</label>
            <input v-model="signalApiUrl" class="input w-full" placeholder="https://signal-api.example.com" type="url" required />
            <p class="text-xs text-gray-500 mt-1">URL of your signal-cli REST API instance.</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Sender Number *</label>
            <input v-model="signalSenderNumber" class="input w-full" placeholder="+33612345678" required />
            <p class="text-xs text-gray-500 mt-1">Phone number registered in signal-cli (E.164 format).</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Recipients (comma-separated) *</label>
            <input v-model="signalRecipients" class="input w-full" placeholder="+33612345678, +33698765432" required />
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1">Cancel</button>
          <button type="submit" :disabled="loading || !form.type" class="flex-1 btn-primary">
            {{ loading ? 'Adding…' : 'Add channel' }}
          </button>
        </div>
      </form>
  </BaseModal>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api/client'
import BaseModal from '../BaseModal.vue'

const { t } = useI18n()

const emit = defineEmits(['close', 'created'])
const form = ref({ name: '', type: '' })
const loading = ref(false)
const error = ref('')

const emailTo = ref('')
const webhookUrl = ref('')
const webhookSecret = ref('')
const webhookTemplate = ref('')
const telegramToken = ref('')
const telegramChatId = ref('')
const telegramChatName = ref('')
const telegramResolving = ref(false)
const telegramResolveError = ref('')
const slackWebhookUrl = ref('')
const pdIntegrationKey = ref('')
const pdSeverity = ref('critical')
const opsApiKey = ref('')
const opsRegion = ref('us')
const opsPriority = ref('P1')
const signalApiUrl = ref('')
const signalSenderNumber = ref('')
const signalRecipients = ref('')
const discordWebhookUrl = ref('')
const mattermostWebhookUrl = ref('')
const teamsWebhookUrl = ref('')

async function resolveTelegram() {
  telegramResolving.value = true
  telegramResolveError.value = ''
  telegramChatName.value = ''
  try {
    const { data } = await api.post('/alerts/telegram/resolve', { bot_token: telegramToken.value })
    telegramChatId.value = data.chat_id
    telegramChatName.value = data.chat_name
  } catch (err) {
    telegramResolveError.value = err.response?.data?.detail || 'Failed to resolve chat ID'
  } finally {
    telegramResolving.value = false
  }
}

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
    case 'signal':
      return { api_url: signalApiUrl.value, sender_number: signalSenderNumber.value, recipients: signalRecipients.value.split(',').map(n => n.trim()).filter(Boolean) }
    case 'discord':
      return { webhook_url: discordWebhookUrl.value }
    case 'mattermost':
      return { webhook_url: mattermostWebhookUrl.value }
    case 'teams':
      return { webhook_url: teamsWebhookUrl.value }
    default:
      return {}
  }
}

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    const payload = { ...form.value, config: buildConfig() }
    if (form.value.type === 'webhook' && webhookTemplate.value) {
      payload.webhook_template = webhookTemplate.value
    }
    await api.post('/alerts/channels', payload)
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to add channel'
  } finally {
    loading.value = false
  }
}
</script>
