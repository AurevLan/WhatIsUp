<template>
  <BaseModal
    :model-value="open"
    :title="t('detection_alert.title')"
    @update:model-value="!$event && $emit('close')"
  >
    <p class="text-sm text-(--text-2) mb-4">
      <slot name="description">{{ t('detection_alert.desc') }}</slot>
    </p>
    <div class="mb-4">
      <label class="block text-sm font-medium text-(--text-2) mb-1">{{ t('detection_alert.channel') }}</label>
      <select
        :value="channelId"
        class="input w-full"
        @change="$emit('update:channelId', $event.target.value)"
      >
        <option v-for="ch in channels" :key="ch.id" :value="ch.id">
          {{ ch.name }} ({{ ch.type }})
        </option>
      </select>
    </div>
    <template #footer>
      <button class="flex-1 text-xs text-(--text-3) hover:text-(--text-1)" @click="$emit('dismiss')">
        {{ dismissLabel || t('detection_alert.dismiss') }}
      </button>
      <button
        class="flex-1 btn-primary disabled:opacity-50"
        :disabled="creating || !channelId"
        @click="$emit('create')"
      >
        {{ creating ? t('detection_alert.creating') : t('detection_alert.create') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import BaseModal from '../BaseModal.vue'

// Generic "detection → notification" bridge modal (axis B). Presentational only;
// the parent owns the channel list + create/dismiss actions (via
// useDetectionAlertBridge). `dismiss` = user declined (parent decides what that
// means per detection); `close` = backdrop/X (just close).
defineProps({
  open: { type: Boolean, default: false },
  channels: { type: Array, default: () => [] },
  channelId: { type: [String, Number], default: '' },
  creating: { type: Boolean, default: false },
  dismissLabel: { type: String, default: '' },
})
defineEmits(['update:channelId', 'create', 'dismiss', 'close'])

const { t } = useI18n()
</script>
