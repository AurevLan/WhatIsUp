<template>
  <!-- Annotations -->
  <div class="card mb-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-sm font-semibold text-(--text-2)">{{ t('monitor_detail.annotations') }}</h2>
      <button @click="state.showForm.value = !state.showForm.value"
        class="btn-ghost btn-sm flex items-center gap-1">
        <span>+</span> {{ t('monitor_detail.add_annotation') }}
      </button>
    </div>

    <div v-if="state.showForm.value" class="flex flex-wrap gap-3 mb-4 p-3 bg-(--bg-surface-2) rounded-lg border border-(--border)">
      <input v-model="state.newAnnotation.value.annotated_at" type="datetime-local"
        class="input text-xs flex-shrink-0" />
      <input v-model="state.newAnnotation.value.content" class="input text-xs flex-1 min-w-48"
        :placeholder="t('monitor_detail.annotation_content')" @keydown.enter="state.add" />
      <button @click="state.add" class="btn-primary btn-sm">{{ t('monitor_detail.add_annotation') }}</button>
      <button @click="state.showForm.value = false" class="btn-ghost btn-sm">{{ t('common.cancel') }}</button>
    </div>

    <div v-if="state.annotations.value.length" class="space-y-1.5">
      <div v-for="a in state.annotations.value" :key="a.id"
        class="flex items-center gap-3 py-2 px-3 rounded-lg bg-(--bg-surface-2) group">
        <span class="w-0.5 h-5 bg-(--accent) rounded-full flex-shrink-0" />
        <div class="flex-1 min-w-0">
          <p class="text-sm text-(--text-1)">{{ a.content }}</p>
          <p class="text-xs text-(--text-3) mt-0.5">
            {{ fmtDateTime(a.annotated_at) }}
            <span v-if="a.created_by" class="ml-2 text-(--text-3)">· {{ a.created_by }}</span>
          </p>
        </div>
        <button @click="state.remove(a.id)"
          class="opacity-0 group-hover:opacity-100 text-xs text-(--down) transition-opacity px-1"
          :aria-label="t('common.delete')">
          ✕
        </button>
      </div>
    </div>
    <p v-else class="text-(--text-3) text-sm text-center py-4">
      No annotations — mark your deployments and interventions here
    </p>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import { useI18n } from 'vue-i18n'
import { AnnotationsStateKey } from './injectionKeys'

defineProps({
  fmtDateTime: { type: Function, required: true },
})

// Provided by MonitorDetailView via provide(AnnotationsStateKey, annotationsState).
// Injection sidesteps vue/no-mutating-props for the intentional
// `state.x.value = …` pattern below.
const state = inject(AnnotationsStateKey)

const { t } = useI18n()
</script>
