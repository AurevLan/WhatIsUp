<template>
  <div class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
      <div class="flex items-center justify-between mb-6">
        <h2 class="text-lg font-semibold text-white">New Group</h2>
        <button @click="$emit('close')" class="text-gray-400 hover:text-white">✕</button>
      </div>

      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Name *</label>
          <input v-model="form.name" class="input w-full" placeholder="My Services" required />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
          <input v-model="form.description" class="input w-full" placeholder="Optional description" />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1">
            Public slug
            <span class="text-gray-500 font-normal">(for status page URL)</span>
          </label>
          <div class="flex items-center gap-2">
            <span class="text-gray-500 text-sm">/status/</span>
            <input v-model="form.public_slug" class="input flex-1" placeholder="my-services"
              pattern="[a-z0-9-]+" />
          </div>
        </div>

        <div v-if="error" class="bg-red-900/40 border border-red-700 rounded p-3 text-sm text-red-300">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">Cancel</button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? 'Creating...' : 'Create Group' }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { groupsApi } from '../../api/monitors'

const emit = defineEmits(['close', 'created'])
const form = ref({ name: '', description: '', public_slug: '' })
const loading = ref(false)
const error = ref('')

async function handleSubmit() {
  loading.value = true
  error.value = ''
  try {
    const payload = { ...form.value }
    if (!payload.public_slug) delete payload.public_slug
    await groupsApi.create(payload)
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create group'
  } finally {
    loading.value = false
  }
}
</script>
