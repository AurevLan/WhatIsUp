<template>
  <div v-if="hasError" role="alert" class="min-h-screen flex items-center justify-center p-6 bg-(--bg-base)">
    <div class="max-w-md w-full bg-(--bg-surface) rounded-lg shadow-lg p-6 border border-[color-mix(in_srgb,var(--down)_35%,transparent)]">
      <div class="flex items-start gap-3 mb-4">
        <AlertTriangle class="w-6 h-6 text-(--down) flex-shrink-0 mt-0.5" />
        <div>
          <h1 class="text-lg font-semibold text-(--text-1)">{{ t('error_boundary.title') }}</h1>
          <p class="mt-1 text-sm text-(--text-2)">{{ t('error_boundary.description') }}</p>
        </div>
      </div>

      <details v-if="errorMessage" class="mb-4 text-xs">
        <summary class="cursor-pointer text-(--text-3) hover:text-(--text-1)">
          {{ t('error_boundary.details') }}
        </summary>
        <pre class="mt-2 p-3 bg-(--bg-surface-2) rounded text-(--text-2) overflow-auto max-h-40 whitespace-pre-wrap">{{ errorMessage }}</pre>
      </details>

      <div class="flex gap-2">
        <button
          type="button"
          class="flex-1 btn-primary"
          @click="reload"
        >
          {{ t('error_boundary.reload') }}
        </button>
        <button
          type="button"
          class="btn-secondary"
          @click="reset"
        >
          {{ t('error_boundary.dismiss') }}
        </button>
      </div>
    </div>
  </div>
  <slot v-else />
</template>

<script setup>
import { ref, onErrorCaptured } from 'vue'
import { useI18n } from 'vue-i18n'
import { AlertTriangle } from 'lucide-vue-next'

const { t } = useI18n()
const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err) => {
  hasError.value = true
  errorMessage.value = err?.stack || err?.message || String(err)
   
  console.error('[ErrorBoundary] caught:', err)
  return false
})

function reload() {
  window.location.reload()
}

function reset() {
  hasError.value = false
  errorMessage.value = ''
}
</script>
