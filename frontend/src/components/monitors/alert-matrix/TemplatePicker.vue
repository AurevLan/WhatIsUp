<template>
  <div>
    <button
      type="button"
      @click="openModal"
      class="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-800 text-xs text-gray-300 hover:border-gray-600 hover:text-white bg-gray-900/40"
    >
      <Sparkles :size="14" />
      <span>{{ t('alert_matrix.templates.trigger') }}</span>
    </button>

    <BaseModal v-model="open" :title="t('alert_matrix.templates.title')" size="md">
      <div class="space-y-3">
        <p class="text-xs text-gray-500">{{ t('alert_matrix.templates.hint') }}</p>

        <div v-if="loading" class="text-sm text-gray-500 text-center py-6">
          {{ t('common.loading') }}
        </div>

        <div v-else-if="!templates.length" class="text-xs text-gray-500 text-center py-6 italic">
          {{ t('alert_matrix.templates.empty') }}
        </div>

        <div v-else class="space-y-2">
          <div
            v-for="tpl in templates"
            :key="tpl.id"
            class="rounded-lg border transition-colors"
            :class="selectedId === tpl.id ? 'border-blue-500/60 bg-blue-500/10' : 'border-gray-800 hover:border-gray-700'"
          >
            <button type="button" @click="selectedId = tpl.id" class="w-full text-left p-3">
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <div class="text-sm font-semibold text-gray-100 flex items-center gap-2">
                    <span>{{ tpl.name }}</span>
                    <span
                      v-if="tpl.is_system"
                      class="text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 border border-gray-700"
                    >{{ t('alert_matrix.templates.system') }}</span>
                  </div>
                  <p v-if="tpl.description" class="text-[11px] text-gray-500 mt-0.5">
                    {{ tpl.description }}
                  </p>
                </div>
                <span class="shrink-0 text-[10px] text-gray-600 uppercase tracking-wide">
                  {{ tpl.rows.length }} {{ t('alert_matrix.templates.rules') }}
                </span>
              </div>
              <div class="mt-2 flex flex-wrap gap-1">
                <span
                  v-for="row in tpl.rows"
                  :key="row.condition"
                  class="inline-block px-2 py-0.5 rounded text-[10px] font-mono bg-gray-800/80 text-gray-300 border border-gray-800"
                >
                  {{ row.condition }}
                </span>
              </div>
            </button>
          </div>
        </div>

        <div
          v-if="hasExistingRows && selectedId"
          class="flex items-start gap-2 rounded-lg border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-[11px] text-amber-300"
        >
          <AlertTriangle :size="14" class="shrink-0 mt-0.5" />
          <span>{{ t('alert_matrix.templates.warn_replace') }}</span>
        </div>
      </div>

      <template #footer>
        <div class="flex-1" />
        <button type="button" @click="close" class="btn-ghost text-xs">
          {{ t('common.cancel') }}
        </button>
        <button
          type="button"
          @click="apply"
          :disabled="!selectedId"
          class="btn-primary text-xs disabled:opacity-40"
        >
          {{ t('alert_matrix.templates.apply') }}
        </button>
      </template>
    </BaseModal>

  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Sparkles, AlertTriangle } from 'lucide-vue-next'
import api from '../../../api/client'
import BaseModal from '../../BaseModal.vue'

const props = defineProps({
  checkType: { type: String, required: true },
  hasExistingRows: { type: Boolean, default: false },
})
const emit = defineEmits(['apply'])
const { t } = useI18n()

const open = ref(false)
const loading = ref(false)
const templates = ref([])
const selectedId = ref(null)

async function openModal() {
  open.value = true
  selectedId.value = null
  loading.value = true
  try {
    const { data } = await api.get(`/alerts/matrix-templates/${props.checkType}`)
    templates.value = data
  } finally {
    loading.value = false
  }
}

function close() {
  open.value = false
  selectedId.value = null
}

const selectedTemplate = computed(() => templates.value.find(tpl => tpl.id === selectedId.value))

function apply() {
  if (!selectedTemplate.value) return
  emit('apply', selectedTemplate.value.rows)
  close()
}
</script>
