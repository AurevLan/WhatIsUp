<template>
  <!-- Quick schedule maintenance modal -->
  <BaseModal v-model="state.showModal.value" :title="t('maintenance.schedule_maintenance')" size="lg">
    <div class="space-y-4">
      <div>
        <label class="text-sm text-(--text-2)">{{ t('common.name') }} <span class="text-(--down)">*</span></label>
        <input v-model="state.form.value.name" class="input w-full mt-1" :placeholder="t('maintenance.name_placeholder')" />
      </div>
      <div>
        <label class="text-sm text-(--text-2)">
          {{ t('maintenance.description_label') }}
          <span class="text-(--text-3)">({{ t('common.optional') }})</span>
        </label>
        <textarea v-model="state.form.value.description" class="input w-full mt-1 resize-none" rows="2"
          :placeholder="t('maintenance.description_placeholder')" />
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="text-sm text-(--text-2)">{{ t('maintenance.starts') }} <span class="text-(--down)">*</span></label>
          <input v-model="state.form.value.starts_at" type="datetime-local" class="input w-full mt-1" />
        </div>
        <div>
          <label class="text-sm text-(--text-2)">{{ t('maintenance.ends') }} <span class="text-(--down)">*</span></label>
          <input v-model="state.form.value.ends_at" type="datetime-local" class="input w-full mt-1" />
        </div>
      </div>
      <div class="flex items-center gap-3 py-1">
        <button type="button" @click="state.form.value.suppress_alerts = !state.form.value.suppress_alerts"
          :aria-label="t('maintenance.suppress_alerts_label')"
          class="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200"
          :class="state.form.value.suppress_alerts ? 'bg-(--accent)' : 'bg-(--bg-surface-2)'">
          <span class="inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform duration-200"
            :class="state.form.value.suppress_alerts ? 'translate-x-4' : 'translate-x-0'" />
        </button>
        <span class="text-sm text-(--text-2) cursor-pointer select-none"
          @click="state.form.value.suppress_alerts = !state.form.value.suppress_alerts">
          {{ t('maintenance.suppress_alerts_label') }}
        </span>
      </div>
    </div>
    <template #footer>
      <button @click="state.showModal.value = false" class="btn-secondary flex-1">{{ t('common.cancel') }}</button>
      <button @click="state.createWindow" :disabled="state.saving.value" class="btn-primary flex-1 disabled:opacity-50">
        {{ state.saving.value ? t('common.loading') : t('common.add') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import BaseModal from '../../BaseModal.vue'
import { MaintenanceStateKey } from './injectionKeys'

// Provided by MonitorDetailView via provide(MaintenanceStateKey, maintenanceState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(MaintenanceStateKey)

const { t } = useI18n()
</script>
