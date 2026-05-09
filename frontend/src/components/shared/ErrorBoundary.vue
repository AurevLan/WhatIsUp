<template>
  <div v-if="hasError" role="alert" class="min-h-screen flex items-center justify-center p-6 bg-gray-50 dark:bg-gray-900">
    <div class="max-w-md w-full bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6 border border-red-200 dark:border-red-800">
      <div class="flex items-start gap-3 mb-4">
        <AlertTriangle class="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
        <div>
          <h1 class="text-lg font-semibold text-gray-900 dark:text-gray-100">{{ t('error_boundary.title') }}</h1>
          <p class="mt-1 text-sm text-gray-600 dark:text-gray-400">{{ t('error_boundary.description') }}</p>
        </div>
      </div>

      <details v-if="errorMessage" class="mb-4 text-xs">
        <summary class="cursor-pointer text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
          {{ t('error_boundary.details') }}
        </summary>
        <pre class="mt-2 p-3 bg-gray-100 dark:bg-gray-900 rounded text-gray-700 dark:text-gray-300 overflow-auto max-h-40 whitespace-pre-wrap">{{ errorMessage }}</pre>
      </details>

      <div class="flex gap-2">
        <button
          type="button"
          class="flex-1 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-md transition"
          @click="reload"
        >
          {{ t('error_boundary.reload') }}
        </button>
        <button
          type="button"
          class="px-4 py-2 bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-900 dark:text-gray-100 font-medium rounded-md transition"
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
  // eslint-disable-next-line no-console
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
