<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="close">
      <div class="card w-full max-w-md" @click.stop>
        <div class="flex justify-between items-center mb-6">
          <h2 class="text-lg font-semibold text-white">{{ t('admin.create_team_title') }}</h2>
          <button @click="close" class="text-gray-500 hover:text-gray-300"><X class="w-5 h-5" /></button>
        </div>
        <form @submit.prevent="submitCreateTeam" class="space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_team_name') }}</label>
            <input v-model="teamCreateForm.name" type="text" class="input w-full" required maxlength="200" />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ t('admin.label_slug') }}</label>
            <input v-model="teamCreateForm.slug" type="text" class="input w-full" :placeholder="t('admin.placeholder_slug')" pattern="^[a-z0-9][a-z0-9-]*$" />
          </div>
          <div v-if="teamError" class="text-red-400 text-sm">{{ teamError }}</div>
          <div class="flex justify-end gap-3 pt-2">
            <button type="button" @click="close" class="btn-secondary">{{ t('common.cancel') }}</button>
            <button type="submit" class="btn-primary" :disabled="submitting">{{ submitting ? t('admin.creating') : t('admin.create_btn') }}</button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { teamsApi } from '../../api/teams'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const submitting = ref(false)
const teamError = ref('')
const teamCreateForm = ref({ name: '', slug: '' })

watch(() => props.modelValue, (open) => {
  if (open) {
    teamCreateForm.value = { name: '', slug: '' }
    teamError.value = ''
  }
})

function close() {
  emit('update:modelValue', false)
}

async function submitCreateTeam() {
  submitting.value = true
  teamError.value = ''
  try {
    const payload = { ...teamCreateForm.value }
    if (!payload.slug) delete payload.slug
    await teamsApi.create(payload)
    emit('update:modelValue', false)
    emit('saved')
  } catch (e) {
    teamError.value = e.response?.data?.detail || t('common.error')
  } finally {
    submitting.value = false
  }
}
</script>
