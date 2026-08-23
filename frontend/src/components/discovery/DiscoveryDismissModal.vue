<template>
  <BaseModal :title="t('discovery.dismiss_title')" @close="$emit('close')">
    <div class="space-y-4">
      <p class="text-sm text-(--text-2)">
        {{ count > 1 ? t('discovery.dismiss_intro_bulk', { n: count }) : t('discovery.dismiss_intro_single') }}
      </p>
      <div>
        <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('discovery.reason_label') }}</label>
        <textarea
          v-model="reason"
          class="input w-full"
          rows="2"
          maxlength="255"
          :placeholder="t('discovery.reason_placeholder')"
        ></textarea>
      </div>
      <div class="flex gap-3 pt-2">
        <button type="button" @click="$emit('close')" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
        <button type="button" @click="$emit('confirm', reason.trim() || null)" class="flex-1 btn-danger">
          {{ t('discovery.dismiss') }}
        </button>
      </div>
    </div>
  </BaseModal>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../BaseModal.vue'

const { t } = useI18n()

defineProps({
  count: { type: Number, default: 1 },
})
defineEmits(['close', 'confirm'])

const reason = ref('')
</script>
