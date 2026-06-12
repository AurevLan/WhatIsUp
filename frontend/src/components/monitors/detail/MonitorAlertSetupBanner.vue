<template>
  <!-- No alert rules banner -->
  <div
    v-if="state.rulesLoaded.value && state.rules.value.length === 0"
    class="mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-[color-mix(in_srgb,var(--warn)_25%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)]"
  >
    <div class="flex items-center gap-2">
      <span class="text-(--warn) text-lg">⚠</span>
      <span class="text-sm text-(--warn)">{{ t('monitors.alert_setup.no_rules_banner') }}</span>
    </div>
    <button
      @click="state.showAutoModal.value = true"
      class="btn-primary text-xs whitespace-nowrap"
    >{{ t('monitors.alert_setup.setup_now') }}</button>
  </div>

  <!-- Auto-alert setup modal -->
  <BaseModal :model-value="state.showAutoModal.value"
    :title="t('monitors.alert_setup.modal_title')"
    @update:model-value="state.showAutoModal.value = $event">
    <div v-if="state.autoChannels.value.length === 0" class="text-sm text-(--text-2) mb-4">
      {{ t('monitors.alert_setup.no_channels') }}
    </div>
    <div v-else class="space-y-2 mb-4">
      <label
        v-for="ch in state.autoChannels.value" :key="ch.id"
        class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
        :class="state.autoSelectedChannels.value.includes(ch.id)
          ? 'border-(--accent-border) bg-(--accent-glow)'
          : 'border-(--border) hover:border-(--border-hover)'"
      >
        <input type="checkbox" :value="ch.id" v-model="state.autoSelectedChannels.value"
          class="rounded bg-(--bg-surface-2) border-(--border) text-(--accent)" />
        <span class="text-sm text-(--text-2)">{{ ch.name }}</span>
        <span class="text-xs text-(--text-3) ml-auto">{{ ch.type }}</span>
      </label>
    </div>
    <template #footer>
      <button @click="state.showAutoModal.value = false" class="flex-1 px-4 py-2 border border-(--border) text-(--text-2) rounded-lg hover:bg-(--bg-surface-2)">
        {{ t('common.cancel') }}
      </button>
      <button @click="state.createAutoRules" :disabled="state.autoSelectedChannels.value.length === 0 || state.autoCreating.value"
        class="flex-1 btn-primary disabled:opacity-50">
        {{ state.autoCreating.value ? t('common.loading') : t('monitors.alert_setup.create_rules') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { AlertSetupStateKey } from './injectionKeys'

// Provided by MonitorDetailView via provide(AlertSetupStateKey, alertsState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(AlertSetupStateKey)

const { t } = useI18n()
</script>
