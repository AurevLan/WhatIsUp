<template>
  <div class="space-y-4">
    <div class="card">
      <div class="flex items-center justify-between mb-3">
        <div>
          <h2 class="text-sm font-semibold text-(--text-1)">{{ t('runbook.title') }}</h2>
          <p class="text-xs text-(--text-3) mt-0.5">{{ t('runbook.subtitle') }}</p>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="!editing"
            class="btn-secondary btn-sm"
            @click="$emit('start-edit')"
          >
            ✎ {{ t('common.edit') }}
          </button>
          <template v-else>
            <button class="btn-secondary btn-sm" @click="$emit('cancel-edit')">
              {{ t('common.cancel') }}
            </button>
            <button
              :disabled="saving"
              class="btn-primary btn-sm disabled:opacity-50"
              @click="$emit('save')"
            >
              {{ saving ? t('common.loading') : t('common.save') }}
            </button>
          </template>
        </div>
      </div>

      <div v-if="editing" class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <textarea
          :value="draft"
          rows="20"
          maxlength="20000"
          :placeholder="t('runbook.placeholder')"
          class="input w-full font-mono text-sm"
          @input="$emit('update:draft', $event.target.value)"
        ></textarea>
        <div
          class="runbook-preview prose prose-invert max-w-none text-sm p-3 rounded-lg border border-(--border) bg-(--bg-surface) overflow-auto"
          v-html="previewHtml"
        ></div>
      </div>

      <div v-else>
        <div
          v-if="monitor.runbook_markdown"
          class="runbook-preview prose prose-invert max-w-none text-sm"
          v-html="renderedHtml"
        ></div>
        <p v-else class="text-sm text-(--text-3) italic">{{ t('runbook.empty') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

defineProps({
  monitor: { type: Object, required: true },
  editing: { type: Boolean, default: false },
  draft: { type: String, default: '' },
  saving: { type: Boolean, default: false },
  renderedHtml: { type: String, default: '' },
  previewHtml: { type: String, default: '' },
})

defineEmits(['start-edit', 'cancel-edit', 'save', 'update:draft'])

const { t } = useI18n()
</script>
