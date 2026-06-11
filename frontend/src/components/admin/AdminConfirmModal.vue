<template>
  <Teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4" @click.self="$emit('update:modelValue', false)">
      <div class="card w-full max-w-sm" @click.stop>
        <h2 class="text-lg font-semibold text-white mb-3">{{ title }}</h2>
        <p class="text-gray-400 text-sm mb-6">
          {{ message }}
        </p>
        <div class="flex justify-end gap-3">
          <button @click="$emit('update:modelValue', false)" class="btn-secondary">{{ t('common.cancel') }}</button>
          <button @click="$emit('confirm')" class="btn-danger" :disabled="busy">
            {{ busy ? t('admin.deleting') : t('common.delete') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
defineEmits(['update:modelValue', 'confirm'])

const { t } = useI18n()
</script>
