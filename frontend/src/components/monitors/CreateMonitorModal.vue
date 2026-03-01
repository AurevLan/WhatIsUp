<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-lg p-6">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-semibold text-white">New Monitor</h2>
        <button @click="$emit('close')" class="text-gray-400 hover:text-white">✕</button>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Name *</label>
          <input v-model="form.name" class="input w-full" placeholder="My Website" required />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">URL *</label>
          <input v-model="form.url" class="input w-full" placeholder="https://example.com" required type="url" />
        </div>

        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Interval (seconds)</label>
            <input v-model.number="form.interval_seconds" class="input w-full" type="number" min="5" max="86400" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Timeout (seconds)</label>
            <input v-model.number="form.timeout_seconds" class="input w-full" type="number" min="1" max="60" />
          </div>
        </div>

        <div class="flex items-center gap-3">
          <input v-model="form.follow_redirects" type="checkbox" id="redirects" class="rounded" />
          <label for="redirects" class="text-sm text-gray-300">Follow redirects</label>
        </div>

        <div class="flex items-center gap-3">
          <input v-model="form.ssl_check_enabled" type="checkbox" id="ssl" class="rounded" />
          <label for="ssl" class="text-sm text-gray-300">Monitor SSL certificate</label>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800 transition-colors">
            Cancel
          </button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? 'Creating...' : 'Create Monitor' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useMonitorStore } from '../../stores/monitors'

const emit = defineEmits(['close', 'created'])
const monitorStore = useMonitorStore()

const form = ref({
  name: '',
  url: '',
  interval_seconds: 60,
  timeout_seconds: 10,
  follow_redirects: true,
  ssl_check_enabled: true,
  expected_status_codes: [200],
})

const loading = ref(false)
const error = ref('')

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    await monitorStore.create(form.value)
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create monitor'
  } finally {
    loading.value = false
  }
}
</script>
