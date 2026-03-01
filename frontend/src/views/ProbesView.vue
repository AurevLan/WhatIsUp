<template>
  <div class="p-8">
    <div class="flex items-center justify-between mb-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Probes</h1>
        <p class="text-gray-400 mt-1">Remote monitoring agents</p>
      </div>
      <button v-if="auth.isSuperadmin" @click="showRegister = true" class="btn-primary">
        + Register Probe
      </button>
    </div>

    <!-- Probe grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <div v-for="probe in probes" :key="probe.id" class="card">
        <div class="flex items-start justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 rounded-full" :class="isOnline(probe) ? 'bg-emerald-400' : 'bg-red-500'"></span>
              <h3 class="font-semibold text-white">{{ probe.name }}</h3>
            </div>
            <p class="text-sm text-gray-400 mt-1">{{ probe.location_name }}</p>
          </div>
          <span class="text-xs px-2 py-1 rounded-full"
            :class="isOnline(probe) ? 'bg-emerald-900/50 text-emerald-400' : 'bg-red-900/50 text-red-400'">
            {{ isOnline(probe) ? 'Online' : 'Offline' }}
          </span>
        </div>

        <div class="mt-4 space-y-1 text-xs text-gray-500">
          <div v-if="probe.latitude && probe.longitude">
            📍 {{ probe.latitude.toFixed(4) }}, {{ probe.longitude.toFixed(4) }}
          </div>
          <div>
            Last seen: {{ probe.last_seen_at ? formatDate(probe.last_seen_at) : 'Never' }}
          </div>
        </div>

        <div v-if="auth.isSuperadmin" class="mt-4 pt-4 border-t border-gray-800">
          <button @click="deactivateProbe(probe)"
            class="text-xs text-red-400 hover:text-red-300">
            Deactivate
          </button>
        </div>
      </div>

      <div v-if="probes.length === 0" class="col-span-full text-center text-gray-500 py-16">
        No probes registered. Install a probe on an external server to start monitoring.
      </div>
    </div>

    <!-- Register probe modal -->
    <RegisterProbeModal v-if="showRegister" @close="showRegister = false" @registered="onRegistered" />

    <!-- Show API key once -->
    <div v-if="newApiKey" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div class="bg-gray-900 border border-amber-700 rounded-2xl w-full max-w-md p-6">
        <h2 class="text-lg font-semibold text-amber-400 mb-4">⚠️ Save this API key</h2>
        <p class="text-sm text-gray-300 mb-4">
          This API key will only be shown once. Copy it now and configure your probe with it.
        </p>
        <div class="bg-gray-800 rounded-lg p-3 font-mono text-sm text-white break-all mb-4">
          {{ newApiKey }}
        </div>
        <button @click="newApiKey = null" class="btn-primary w-full">I've copied the key</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { probesApi } from '../api/probes'
import RegisterProbeModal from '../components/probes/RegisterProbeModal.vue'

const auth = useAuthStore()
const probes = ref([])
const showRegister = ref(false)
const newApiKey = ref(null)

function isOnline(probe) {
  if (!probe.last_seen_at) return false
  const lastSeen = new Date(probe.last_seen_at)
  const diff = (Date.now() - lastSeen.getTime()) / 1000
  return diff < 120 // Online if seen in last 2 minutes
}

function formatDate(dt) {
  return new Date(dt).toLocaleString('fr-FR')
}

async function loadProbes() {
  try {
    const { data } = await probesApi.list()
    probes.value = data
  } catch {}
}

async function deactivateProbe(probe) {
  if (confirm(`Deactivate probe "${probe.name}"?`)) {
    await probesApi.deactivate(probe.id)
    await loadProbes()
  }
}

function onRegistered(data) {
  showRegister.value = false
  newApiKey.value = data.api_key
  loadProbes()
}

onMounted(loadProbes)
</script>
