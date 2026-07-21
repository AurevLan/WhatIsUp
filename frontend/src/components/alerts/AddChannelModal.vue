<template>
  <BaseModal :title="t('alerts.channel_form.title')" @close="$emit('close')">

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.name') }} *</label>
          <input v-model="form.name" class="input w-full" :placeholder="t('alerts.channel_form.name_placeholder')" required />
        </div>

        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.type') }} *</label>
          <select v-model="form.type" class="input w-full" required>
            <option value="">{{ t('alerts.channel_form.type_placeholder') }}</option>
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
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.recipients') }} *</label>
            <input v-model="emailTo" class="input w-full" placeholder="alert@example.com, ops@example.com" required />
          </div>
        </div>

        <!-- Webhook config -->
        <div v-if="form.type === 'webhook'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.url') }} *</label>
            <input v-model="webhookUrl" class="input w-full" placeholder="https://hooks.slack.com/..." type="url" required />
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.secret_hmac') }}</label>
            <input v-model="webhookSecret" class="input w-full" :placeholder="t('alerts.channel_form.secret_placeholder')" />
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.webhook_template') }}</label>
            <textarea
              v-model="webhookTemplate"
              class="input w-full font-mono text-xs"
              rows="5"
              :placeholder="t('alerts.webhook_template_placeholder')"
            ></textarea>
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.webhook_template_hint') }}</p>
          </div>
        </div>

        <!-- Slack config -->
        <div v-if="form.type === 'slack'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.webhook_url') }} *</label>
            <input v-model="slackWebhookUrl" class="input w-full" placeholder="https://hooks.slack.com/services/..." type="url" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.slack_hint') }}</p>
          </div>
        </div>

        <!-- Discord config -->
        <div v-if="form.type === 'discord'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.webhook_url') }} *</label>
            <input v-model="discordWebhookUrl" class="input w-full" placeholder="https://discord.com/api/webhooks/..." type="url" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.discord_hint') }}</p>
          </div>
        </div>

        <!-- Mattermost config -->
        <div v-if="form.type === 'mattermost'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.webhook_url') }} *</label>
            <input v-model="mattermostWebhookUrl" class="input w-full" placeholder="https://mattermost.example.com/hooks/..." type="url" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.mattermost_hint') }}</p>
          </div>
        </div>

        <!-- Teams config -->
        <div v-if="form.type === 'teams'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.webhook_url') }} *</label>
            <input v-model="teamsWebhookUrl" class="input w-full" placeholder="https://prod-XX.westus.logic.azure.com/..." type="url" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.teams_hint') }}</p>
          </div>
        </div>

        <!-- Telegram config -->
        <div v-if="form.type === 'telegram'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.bot_token') }} *</label>
            <div class="flex gap-2">
              <input v-model="telegramToken" class="input flex-1" placeholder="1234567890:ABC..." required />
              <button
                type="button"
                @click="resolveTelegram"
                :disabled="!telegramToken || telegramResolving"
                class="btn-primary whitespace-nowrap"
              >
                {{ telegramResolving ? '…' : t('alerts.channel_form.fetch_chat_id') }}
              </button>
            </div>
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.telegram_hint') }}</p>
          </div>
          <div v-if="telegramChatName" class="flex items-center gap-2 bg-[color-mix(in_srgb,var(--up)_10%,transparent)] border border-[color-mix(in_srgb,var(--up)_25%,transparent)] rounded-lg px-3 py-2 text-sm text-(--up)">
            <span>✅</span>
            <span>{{ t('alerts.channel_form.connected_to') }} <strong>{{ telegramChatName }}</strong> (ID: {{ telegramChatId }})</span>
          </div>
          <div v-if="telegramResolveError" class="bg-[color-mix(in_srgb,var(--down)_10%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded-lg px-3 py-2 text-sm text-(--down)">
            {{ telegramResolveError }}
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.chat_id') }} *</label>
            <input v-model="telegramChatId" class="input w-full" :placeholder="t('alerts.channel_form.chat_id_placeholder')" required />
          </div>
        </div>

        <!-- PagerDuty config -->
        <div v-if="form.type === 'pagerduty'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.integration_key') }} *</label>
            <input v-model="pdIntegrationKey" class="input w-full" placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.pagerduty_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.severity') }}</label>
            <select v-model="pdSeverity" class="input w-full">
              <option value="critical">{{ t('alerts.channel_form.severity_critical') }}</option>
              <option value="error">{{ t('alerts.channel_form.severity_error') }}</option>
              <option value="warning">{{ t('alerts.channel_form.severity_warning') }}</option>
              <option value="info">{{ t('alerts.channel_form.severity_info') }}</option>
            </select>
          </div>
        </div>

        <!-- Opsgenie config -->
        <div v-if="form.type === 'opsgenie'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.api_key') }} *</label>
            <input v-model="opsApiKey" class="input w-full" placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.opsgenie_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.region') }}</label>
            <select v-model="opsRegion" class="input w-full">
              <option value="us">US (api.opsgenie.com)</option>
              <option value="eu">EU (api.eu.opsgenie.com)</option>
            </select>
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.priority') }}</label>
            <select v-model="opsPriority" class="input w-full">
              <option value="P1">{{ t('alerts.channel_form.priority_p1') }}</option>
              <option value="P2">{{ t('alerts.channel_form.priority_p2') }}</option>
              <option value="P3">{{ t('alerts.channel_form.priority_p3') }}</option>
              <option value="P4">{{ t('alerts.channel_form.priority_p4') }}</option>
              <option value="P5">{{ t('alerts.channel_form.priority_p5') }}</option>
            </select>
          </div>
        </div>

        <!-- Signal config -->
        <div v-if="form.type === 'signal'" class="space-y-3">
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.signal_api_url') }} *</label>
            <input v-model="signalApiUrl" class="input w-full" placeholder="https://signal-api.example.com" type="url" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.signal_api_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.sender_number') }} *</label>
            <input v-model="signalSenderNumber" class="input w-full" placeholder="+33612345678" required />
            <p class="text-xs text-(--text-3) mt-1">{{ t('alerts.channel_form.sender_number_hint') }}</p>
          </div>
          <div>
            <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('alerts.channel_form.recipients') }} *</label>
            <input v-model="signalRecipients" class="input w-full" placeholder="+33612345678, +33698765432" required />
          </div>
        </div>

        <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_10%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
          <button type="submit" :disabled="loading || !form.type" class="flex-1 btn-primary">
            {{ loading ? t('alerts.channel_form.submitting') : t('alerts.channel_form.submit') }}
          </button>
        </div>
      </form>
  </BaseModal>
</template>

<script setup>
import { ref } from 'vue'
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
    const { data } = await api.post('/alerts/telegram/resolve', { bot_token: telegramToken.value }, { skipErrorToast: true })
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
    await api.post('/alerts/channels', payload, { skipErrorToast: true })
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to add channel'
  } finally {
    loading.value = false
  }
}
</script>
