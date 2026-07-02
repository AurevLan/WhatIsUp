<template>
  <BaseModal title="New Group" @close="$emit('close')">
      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">Name *</label>
          <input v-model="form.name" class="input w-full" placeholder="My Services" required />
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">Description</label>
          <input v-model="form.description" class="input w-full" placeholder="Optional description" />
        </div>
        <div>
          <label class="block text-sm font-medium text-(--text-2) mb-1">
            Public slug
            <span class="text-(--text-3) font-normal">(for status page URL)</span>
          </label>
          <div class="flex items-center gap-2">
            <span class="text-(--text-3) text-sm">/status/</span>
            <input v-model="form.public_slug" class="input flex-1" placeholder="my-services"
              pattern="[a-z0-9-]+" />
          </div>
        </div>

        <div v-if="error" class="bg-[color-mix(in_srgb,var(--down)_12%,transparent)] border border-[color-mix(in_srgb,var(--down)_30%,transparent)] rounded p-3 text-sm text-(--down)">
          {{ error }}
        </div>

        <div class="flex gap-3 pt-2">
          <button type="button" @click="$emit('close')" class="btn-secondary flex-1">Cancel</button>
          <button type="submit" :disabled="loading" class="flex-1 btn-primary">
            {{ loading ? 'Creating...' : 'Create Group' }}
          </button>
        </div>
      </form>
  </BaseModal>
</template>

<script setup>
import { ref } from 'vue'
import { groupsApi } from '../../api/monitors'
import BaseModal from '../BaseModal.vue'

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
    await groupsApi.create(payload, { skipErrorToast: true })
    emit('created')
  } catch (err) {
    error.value = err.response?.data?.detail || 'Failed to create group'
  } finally {
    loading.value = false
  }
}
</script>
