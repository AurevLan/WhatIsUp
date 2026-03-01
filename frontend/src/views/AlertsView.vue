<template>
  <div class="p-8">
    <h1 class="text-2xl font-bold text-white mb-8">Alerts</h1>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <!-- Alert Channels -->
      <div>
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-lg font-semibold text-white">Channels</h2>
          <button @click="showAddChannel = true" class="text-sm btn-primary">+ Add Channel</button>
        </div>

        <div class="space-y-3">
          <div v-for="channel in channels" :key="channel.id" class="card flex items-center gap-4">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center text-lg"
              :class="channelIcon(channel.type).bg">
              {{ channelIcon(channel.type).emoji }}
            </div>
            <div class="flex-1">
              <p class="font-medium text-white">{{ channel.name }}</p>
              <p class="text-xs text-gray-500 capitalize">{{ channel.type }}</p>
            </div>
            <button @click="deleteChannel(channel)" class="text-gray-600 hover:text-red-400">✕</button>
          </div>
          <p v-if="!channels.length" class="text-gray-500 text-sm text-center py-8">
            No channels configured yet.
          </p>
        </div>
      </div>

      <!-- Recent Alert Events -->
      <div>
        <h2 class="text-lg font-semibold text-white mb-4">Recent Events</h2>
        <div class="space-y-2">
          <div v-for="event in events" :key="event.id" class="card">
            <div class="flex items-center gap-3">
              <span class="text-xs font-medium px-2 py-0.5 rounded-full"
                :class="event.status === 'sent' ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
                {{ event.status }}
              </span>
              <span class="text-xs text-gray-400">{{ formatDate(event.sent_at) }}</span>
            </div>
            <p class="text-xs text-gray-500 mt-1 font-mono truncate">
              Incident: {{ event.incident_id.slice(0, 8) }}...
            </p>
          </div>
          <p v-if="!events.length" class="text-gray-500 text-sm text-center py-8">
            No alert events yet.
          </p>
        </div>
      </div>
    </div>

    <!-- Add Channel Modal placeholder -->
    <AddChannelModal v-if="showAddChannel" @close="showAddChannel = false" @created="loadData" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/client'
import AddChannelModal from '../components/alerts/AddChannelModal.vue'

const channels = ref([])
const events = ref([])
const showAddChannel = ref(false)

function channelIcon(type) {
  const map = {
    email: { emoji: '📧', bg: 'bg-blue-900/50' },
    webhook: { emoji: '🔗', bg: 'bg-purple-900/50' },
    telegram: { emoji: '✈️', bg: 'bg-sky-900/50' },
  }
  return map[type] || { emoji: '🔔', bg: 'bg-gray-800' }
}

function formatDate(dt) {
  return new Date(dt).toLocaleString('fr-FR')
}

async function loadData() {
  showAddChannel.value = false
  const [chResp, evResp] = await Promise.all([
    api.get('/alerts/channels'),
    api.get('/alerts/events'),
  ])
  channels.value = chResp.data
  events.value = evResp.data
}

async function deleteChannel(channel) {
  if (confirm(`Delete channel "${channel.name}"?`)) {
    await api.delete(`/alerts/channels/${channel.id}`)
    await loadData()
  }
}

onMounted(loadData)
</script>
