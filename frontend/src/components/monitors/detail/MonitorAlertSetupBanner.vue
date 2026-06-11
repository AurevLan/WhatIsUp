<template>
  <!-- No alert rules banner -->
  <div
    v-if="state.rulesLoaded.value && state.rules.value.length === 0"
    class="mb-4 flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-amber-800/40 bg-amber-900/20"
  >
    <div class="flex items-center gap-2">
      <span class="text-amber-400 text-lg">⚠</span>
      <span class="text-sm text-amber-300">{{ t('monitors.alert_setup.no_rules_banner') }}</span>
    </div>
    <button
      @click="state.showAutoModal.value = true"
      class="btn-primary text-xs whitespace-nowrap"
    >{{ t('monitors.alert_setup.setup_now') }}</button>
  </div>

  <!-- Auto-alert setup modal -->
  <div v-if="state.showAutoModal.value" class="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-2xl w-full max-w-md p-6">
      <h2 class="text-lg font-semibold text-white mb-4">{{ t('monitors.alert_setup.modal_title') }}</h2>
      <div v-if="state.autoChannels.value.length === 0" class="text-sm text-gray-400 mb-4">
        {{ t('monitors.alert_setup.no_channels') }}
      </div>
      <div v-else class="space-y-2 mb-4">
        <label
          v-for="ch in state.autoChannels.value" :key="ch.id"
          class="flex items-center gap-2 px-3 py-2 rounded-lg border cursor-pointer transition-colors"
          :class="state.autoSelectedChannels.value.includes(ch.id)
            ? 'border-blue-600/60 bg-blue-950/30'
            : 'border-gray-800 hover:border-gray-700'"
        >
          <input type="checkbox" :value="ch.id" v-model="state.autoSelectedChannels.value"
            class="rounded bg-gray-800 border-gray-600 text-blue-500" />
          <span class="text-sm text-gray-300">{{ ch.name }}</span>
          <span class="text-xs text-gray-600 ml-auto">{{ ch.type }}</span>
        </label>
      </div>
      <div class="flex gap-3">
        <button @click="state.showAutoModal.value = false" class="flex-1 px-4 py-2 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-800">
          {{ t('common.cancel') }}
        </button>
        <button @click="state.createAutoRules" :disabled="state.autoSelectedChannels.value.length === 0 || state.autoCreating.value"
          class="flex-1 btn-primary disabled:opacity-50">
          {{ state.autoCreating.value ? t('common.loading') : t('monitors.alert_setup.create_rules') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertSetupStateKey } from './injectionKeys'

// Provided by MonitorDetailView via provide(AlertSetupStateKey, alertsState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(AlertSetupStateKey)

const { t } = useI18n()
</script>
