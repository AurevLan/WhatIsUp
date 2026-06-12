<template>
  <BaseModal
    :model-value="modelValue"
    :title="title"
    :message="message"
    size="sm"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <template #footer>
      <div class="flex justify-end gap-3 w-full">
        <button @click="$emit('update:modelValue', false)" class="btn-secondary">{{ t('common.cancel') }}</button>
        <button @click="$emit('confirm')" class="btn-danger" :disabled="busy">
          {{ busy ? t('admin.deleting') : t('common.delete') }}
        </button>
      </div>
    </template>
  </BaseModal>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import BaseModal from '../BaseModal.vue'

defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  busy: { type: Boolean, default: false },
})
defineEmits(['update:modelValue', 'confirm'])

const { t } = useI18n()
</script>
