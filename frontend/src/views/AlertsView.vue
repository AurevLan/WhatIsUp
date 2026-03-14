<template>
  <div class="p-8">
    <h1 class="text-2xl font-bold text-white mb-8">{{ t('alerts.title') }}</h1>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
      <!-- Alert Channels -->
      <div>
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-white">{{ t('alerts.channels') }}</h2>
          <button @click="showAddChannel = true" class="text-sm btn-primary">+ {{ t('alerts.add_channel') }}</button>
        </div>
        <div class="space-y-3">
          <div v-for="channel in channels" :key="channel.id" class="card flex items-center gap-4">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0"
              :class="channelIcon(channel.type).bg">
              {{ channelIcon(channel.type).emoji }}
            </div>
            <div class="flex-1 min-w-0">
              <p class="font-medium text-white truncate">{{ channel.name }}</p>
              <p class="text-xs text-gray-500 capitalize">{{ channel.type }}</p>
            </div>
            <button @click="deleteChannel(channel)" class="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0">✕</button>
          </div>
          <p v-if="!channels.length" class="text-gray-500 text-sm text-center py-8">
            {{ t('alerts.no_channels') }}
          </p>
        </div>
      </div>

      <!-- Recent Alert Events -->
      <div>
        <h2 class="text-lg font-semibold text-white mb-4">Recent events</h2>
        <div class="space-y-2">
          <div v-for="event in events" :key="event.id" class="card">
            <div class="flex items-center gap-3">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0"
                :class="event.status === 'sent' ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
                {{ event.status }}
              </span>
              <span class="text-xs text-gray-400">{{ formatDate(event.sent_at) }}</span>
              <span class="text-xs text-gray-500 truncate font-mono">{{ channelName(event.channel_id) }}</span>
            </div>
            <p class="text-xs text-gray-500 mt-1 font-mono truncate">
              Incident {{ event.incident_id.slice(0, 8) }}…
            </p>
          </div>
          <p v-if="!events.length" class="text-gray-500 text-sm text-center py-8">
            No events yet.
          </p>
        </div>
      </div>
    </div>

    <!-- Alert Rules -->
    <div>
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-white">{{ t('alerts.title') }}</h2>
        <button @click="showAddRule = true" :disabled="!channels.length" class="text-sm btn-primary disabled:opacity-40 disabled:cursor-not-allowed">
          + {{ t('alerts.add_rule') }}
        </button>
      </div>
      <p v-if="!channels.length" class="text-xs text-amber-400 mb-3">
        ⚠ Créez d'abord au moins un canal pour pouvoir configurer des règles.
      </p>

      <div v-if="rules.length === 0 && channels.length" class="text-gray-500 text-sm text-center py-8">
        {{ t('alerts.no_rules') }}
      </div>

      <div class="space-y-3">
        <div v-for="rule in rules" :key="rule.id" class="card">
          <div class="flex items-start justify-between gap-4">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-medium text-white">{{ targetName(rule) }}</span>
                <span class="text-xs px-2 py-0.5 rounded-full font-mono"
                  :class="rule.monitor_id ? 'bg-blue-900/40 text-blue-300' : 'bg-purple-900/40 text-purple-300'">
                  {{ rule.monitor_id ? 'monitor' : 'groupe' }}
                </span>
              </div>
              <div class="mt-2 flex items-center gap-2 flex-wrap">
                <span class="text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-300 font-mono">
                  {{ conditionLabel(rule.condition) }}
                  <span v-if="rule.threshold_value != null">{{ conditionUnit(rule.condition, rule.threshold_value) }}</span>
                </span>
                <span v-if="rule.min_duration_seconds" class="text-xs text-gray-500">· après {{ rule.min_duration_seconds }}s</span>
                <span v-if="rule.renotify_after_minutes" class="text-xs text-gray-500">· ré-alerte {{ rule.renotify_after_minutes }}min</span>
                <span v-if="rule.digest_minutes" class="text-xs text-blue-500">· digest {{ rule.digest_minutes }}min</span>
              </div>
              <div class="mt-2 flex items-center gap-1.5 flex-wrap">
                <span v-for="ch in rule.channels" :key="ch.id"
                  class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-gray-800 text-gray-300">
                  {{ channelIcon(ch.type).emoji }} {{ ch.name }}
                </span>
              </div>
            </div>
            <button @click="deleteRule(rule)" class="text-gray-600 hover:text-red-400 transition-colors flex-shrink-0">✕</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Add Channel Modal -->
    <AddChannelModal v-if="showAddChannel" @close="showAddChannel = false" @created="loadData" />

    <!-- Add Rule Modal -->
    <div v-if="showAddRule" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div class="flex items-center justify-between mb-6">
          <h2 class="text-lg font-semibold text-white">{{ t('alerts.add_rule') }}</h2>
          <button @click="showAddRule = false" class="text-gray-400 hover:text-white">✕</button>
        </div>

        <form @submit.prevent="createRule" class="space-y-4">
          <!-- Target type -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">Cible *</label>
            <div class="grid grid-cols-2 gap-2 mb-2">
              <button type="button" @click="ruleForm.target_type = 'monitor'; ruleForm.target_id = ''"
                class="py-2 px-3 rounded-lg border text-sm font-medium transition-colors"
                :class="ruleForm.target_type === 'monitor'
                  ? 'bg-blue-600 border-blue-500 text-white'
                  : 'border-gray-700 text-gray-400 hover:border-gray-600'">
                Monitor
              </button>
              <button type="button" @click="ruleForm.target_type = 'group'; ruleForm.target_id = ''"
                class="py-2 px-3 rounded-lg border text-sm font-medium transition-colors"
                :class="ruleForm.target_type === 'group'
                  ? 'bg-purple-600 border-purple-500 text-white'
                  : 'border-gray-700 text-gray-400 hover:border-gray-600'">
                Groupe
              </button>
            </div>
            <select v-model="ruleForm.target_id" class="input w-full" required>
              <option value="">-- Sélectionner --</option>
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

          <!-- Condition -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Condition *</label>
            <select v-model="ruleForm.condition" class="input w-full" required>
              <option value="any_down">Alerte si au moins une sonde détecte une panne</option>
              <option value="all_down">Alerte si toutes les sondes détectent une panne (panne globale)</option>
              <option value="ssl_expiry">Expiration du certificat SSL imminente</option>
              <option value="response_time_above">Temps de réponse / résolution dépassé(e)</option>
              <option value="uptime_below">Uptime inférieur au seuil</option>
            </select>
          </div>

          <!-- Threshold -->
          <div v-if="ruleForm.condition === 'response_time_above'">
            <label class="block text-sm font-medium text-gray-300 mb-1">Seuil (ms) *</label>
            <input v-model.number="ruleForm.threshold_value" class="input w-full" type="number" min="1" max="60000" placeholder="ex: 2000" required />
          </div>
          <div v-if="ruleForm.condition === 'uptime_below'">
            <label class="block text-sm font-medium text-gray-300 mb-1">Seuil uptime (%) *</label>
            <input v-model.number="ruleForm.threshold_value" class="input w-full" type="number" min="0" max="100" step="0.1" placeholder="ex: 95" required />
          </div>

          <!-- Min duration -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">
              Durée minimale avant alerte (s)
              <span class="text-gray-500 font-normal">— 0 = immédiat</span>
            </label>
            <input v-model.number="ruleForm.min_duration_seconds" class="input w-full" type="number" min="0" max="3600" />
          </div>

          <!-- Renotify -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">
              Ré-notification toutes les (min)
              <span class="text-gray-500 font-normal">— vide = une seule alerte</span>
            </label>
            <input v-model.number="ruleForm.renotify_after_minutes" class="input w-full" type="number" min="1" max="10080" placeholder="ex: 60" />
          </div>

          <!-- Digest -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">
              Digest — regrouper les alertes (min)
              <span class="text-gray-500 font-normal">— 0 = désactivé, sinon regroupe sur N minutes</span>
            </label>
            <input v-model.number="ruleForm.digest_minutes" class="input w-full" type="number" min="0" max="1440" placeholder="ex: 30" />
          </div>

          <!-- Channels -->
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-2">Canaux *</label>
            <div class="space-y-2">
              <label v-for="ch in channels" :key="ch.id" class="flex items-center gap-3 cursor-pointer">
                <input type="checkbox" :value="ch.id" v-model="ruleForm.channel_ids" class="w-4 h-4" />
                <span class="text-sm text-gray-300">
                  {{ channelIcon(ch.type).emoji }} {{ ch.name }}
                  <span class="text-gray-500 text-xs capitalize">({{ ch.type }})</span>
                </span>
              </label>
            </div>
          </div>

          <div v-if="ruleError" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
            {{ ruleError }}
          </div>

          <div class="flex gap-3 pt-2">
            <button type="button" @click="showAddRule = false"
              class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">
              {{ t('common.cancel') }}
            </button>
            <button type="submit" :disabled="ruleLoading || !ruleForm.target_id || !ruleForm.channel_ids.length"
              class="flex-1 btn-primary disabled:opacity-40 disabled:cursor-not-allowed">
              {{ ruleLoading ? t('common.loading') : t('alerts.add_rule') }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'
import { monitorsApi, groupsApi } from '../api/monitors'
import AddChannelModal from '../components/alerts/AddChannelModal.vue'

const { t } = useI18n()

const channels = ref([])
const events = ref([])
const rules = ref([])
const allMonitors = ref([])
const allGroups = ref([])
const showAddChannel = ref(false)
const showAddRule = ref(false)
const ruleLoading = ref(false)
const ruleError = ref('')

const ruleForm = ref({
  target_type: 'monitor',
  target_id: '',
  condition: 'any_down',
  threshold_value: null,
  min_duration_seconds: 0,
  renotify_after_minutes: null,
  digest_minutes: 0,
  channel_ids: [],
})

function channelIcon(type) {
  const map = {
    email:     { emoji: '📧', bg: 'bg-blue-900/50' },
    webhook:   { emoji: '🔗', bg: 'bg-purple-900/50' },
    telegram:  { emoji: '✈️', bg: 'bg-sky-900/50' },
    slack:     { emoji: '💬', bg: 'bg-emerald-900/50' },
    pagerduty: { emoji: '🔔', bg: 'bg-green-900/50' },
    opsgenie:  { emoji: '🚨', bg: 'bg-orange-900/50' },
  }
  return map[type] || { emoji: '🔔', bg: 'bg-gray-800' }
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

function conditionLabel(cond) {
  const map = {
    any_down: 'Panne détectée (any)',
    all_down: 'Panne globale (all)',
    ssl_expiry: 'Expiration SSL',
    response_time_above: 'Temps de réponse >',
    uptime_below: 'Uptime <',
  }
  return map[cond] || cond
}

function conditionUnit(cond, val) {
  if (cond === 'response_time_above') return ` ${val}ms`
  if (cond === 'uptime_below') return ` ${val}%`
  return ''
}

function formatDate(dt) {
  return new Date(dt).toLocaleString('fr-FR')
}

async function loadData() {
  showAddChannel.value = false
  showAddRule.value = false
  const [chResp, evResp, rulesResp] = await Promise.all([
    api.get('/alerts/channels'),
    api.get('/alerts/events'),
    api.get('/alerts/rules'),
  ])
  channels.value = chResp.data
  events.value = evResp.data
  rules.value = rulesResp.data
}

async function deleteChannel(channel) {
  if (confirm(`Supprimer le canal "${channel.name}" ?`)) {
    await api.delete(`/alerts/channels/${channel.id}`)
    await loadData()
  }
}

async function deleteRule(rule) {
  if (confirm('Supprimer cette règle ?')) {
    await api.delete(`/alerts/rules/${rule.id}`)
    await loadData()
  }
}

async function createRule() {
  ruleLoading.value = true
  ruleError.value = ''
  try {
    const payload = {
      condition: ruleForm.value.condition,
      min_duration_seconds: ruleForm.value.min_duration_seconds || 0,
      channel_ids: ruleForm.value.channel_ids,
    }
    if (ruleForm.value.target_type === 'monitor') {
      payload.monitor_id = ruleForm.value.target_id
    } else {
      payload.group_id = ruleForm.value.target_id
    }
    if (ruleForm.value.threshold_value != null) {
      payload.threshold_value = ruleForm.value.threshold_value
    }
    if (ruleForm.value.renotify_after_minutes) {
      payload.renotify_after_minutes = ruleForm.value.renotify_after_minutes
    }
    if (ruleForm.value.digest_minutes) {
      payload.digest_minutes = ruleForm.value.digest_minutes
    }
    await api.post('/alerts/rules', payload)
    ruleForm.value = {
      target_type: 'monitor', target_id: '', condition: 'any_down',
      threshold_value: null, min_duration_seconds: 0,
      renotify_after_minutes: null, digest_minutes: 0, channel_ids: [],
    }
    await loadData()
  } catch (err) {
    ruleError.value = err.response?.data?.detail || 'Erreur lors de la création de la règle'
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
})
</script>
