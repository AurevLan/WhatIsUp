<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-semibold text-white">Register Probe</h2>
        <button @click="$emit('close')" class="text-gray-400 hover:text-white">✕</button>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Probe Name *</label>
          <input v-model="form.name" class="input w-full" placeholder="paris-probe-01" required />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Location *</label>
          <input v-model="form.location_name" class="input w-full" placeholder="Paris, France" required />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Latitude</label>
            <input v-model.number="form.latitude" class="input w-full" type="number" step="0.0001" min="-90" max="90" placeholder="48.8566" />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-300 mb-1">Longitude</label>
            <input v-model.number="form.longitude" class="input w-full" type="number" step="0.0001" min="-180" max="180" placeholder="2.3522" />
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">Cancel</button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? 'Registering...' : 'Register' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { probesApi } from '../../api/probes'

const emit = defineEmits(['close', 'registered'])
const form = ref({ name: '', location_name: '', latitude: null, longitude: null })
const loading = ref(false)
const error = ref('')

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await probesApi.register(form.value)
    emit('registered', data)
  } catch (err) {
    error.value = err.response?.data?.detail || 'Registration failed'
  } finally {
    loading.value = false
  }
}
</script>
