<template>
  <BaseModal v-model="open" :title="title" size="lg">
    <form @submit.prevent="submit" class="space-y-4">
      <div>
        <label class="block text-xs text-gray-400 mb-1">{{ t('alert_matrix.templates.editor.name') }}</label>
        <input v-model="form.name" type="text" class="input w-full" required maxlength="100" />
      </div>

      <div>
        <label class="block text-xs text-gray-400 mb-1">{{ t('alert_matrix.templates.editor.description') }}</label>
        <textarea v-model="form.description" class="input w-full" rows="2" />
      </div>

      <div>
        <label class="block text-xs text-gray-400 mb-1">{{ t('alert_matrix.templates.editor.check_type') }}</label>
        <select v-model="form.check_type" class="input w-full" :disabled="isEdit">
          <option v-for="ct in checkTypes" :key="ct" :value="ct">{{ ct }}</option>
        </select>
      </div>

      <div>
        <div class="flex items-center justify-between mb-2">
          <label class="text-xs text-gray-400">{{ t('alert_matrix.templates.editor.rules') }}</label>
          <button
            type="button"
            @click="addRow"
            :disabled="!availableConditions.length"
            class="text-xs text-blue-400 hover:text-blue-300 disabled:opacity-40"
          >+ {{ t('alert_matrix.add_rule') }}</button>
        </div>
        <div v-if="!form.rows.length" class="text-xs text-gray-500 italic text-center py-3">
          {{ t('alert_matrix.templates.editor.no_rules') }}
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="(row, idx) in form.rows"
            :key="idx"
            class="rounded-lg border border-gray-800 bg-gray-900/40 p-3 space-y-2"
          >
            <div class="flex items-center justify-between gap-2">
              <select v-model="row.condition" class="input text-xs flex-1 font-mono">
                <option
                  v-for="cond in conditionOptions(row.condition)"
                  :key="cond"
                  :value="cond"
                >{{ cond }}</option>
              </select>
              <button
                type="button"
                @click="removeRow(idx)"
                class="text-gray-600 hover:text-red-400 text-sm px-2"
              >✕</button>
            </div>
            <div class="grid grid-cols-2 gap-2 text-[11px] text-gray-400">
              <label v-if="needsThreshold(row.condition)" class="flex items-center gap-1.5">
                <span class="shrink-0">{{ t('alert_matrix.threshold') }}</span>
                <input v-model.number="row.threshold_value" type="number" min="0" class="input text-xs w-full py-1" />
              </label>
              <label v-if="row.condition === 'anomaly_detection'" class="flex items-center gap-1.5">
                <span class="shrink-0">{{ t('alert_matrix.zscore_threshold') }}</span>
                <input v-model.number="row.anomaly_zscore_threshold" type="number" min="1" step="0.1" class="input text-xs w-full py-1" />
              </label>
              <label v-if="row.condition === 'response_time_above_baseline'" class="flex items-center gap-1.5">
                <span class="shrink-0">baseline_factor</span>
                <input v-model.number="row.baseline_factor" type="number" min="1.1" step="0.1" class="input text-xs w-full py-1" />
              </label>
              <label class="flex items-center gap-1.5">
                <span class="shrink-0">{{ t('alert_matrix.min_duration') }}</span>
                <input v-model.number="row.min_duration_seconds" type="number" min="0" class="input text-xs w-full py-1" />
              </label>
              <label class="flex items-center gap-1.5">
                <span class="shrink-0">{{ t('alert_matrix.renotify') }}</span>
                <input v-model.number="row.renotify_after_minutes" type="number" min="1" class="input text-xs w-full py-1" />
              </label>
            </div>
          </div>
        </div>
      </div>

      <p v-if="error" class="text-xs text-red-400">{{ error }}</p>
    </form>

    <template #footer>
      <button
        v-if="isEdit && !template?.is_system"
        type="button"
        @click="remove"
        class="btn-ghost text-xs text-red-400 hover:text-red-300"
      >{{ t('common.delete') }}</button>
      <div class="flex-1" />
      <button type="button" @click="close" class="btn-ghost text-xs">{{ t('common.cancel') }}</button>
      <button type="button" @click="submit" :disabled="saving" class="btn-primary text-xs">
        {{ saving ? t('common.loading') : t('common.save') }}
      </button>
    </template>
  </BaseModal>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../../api/client'
import BaseModal from '../../BaseModal.vue'
import {
  CHECK_TYPES as checkTypes,
  CONDITIONS_BY_TYPE,
  needsThreshold as isThresholdCondition,
} from '../../../constants/alertMatrix'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  template: { type: Object, default: null },
  defaultCheckType: { type: String, default: 'http' },
})
const emit = defineEmits(['update:modelValue', 'saved'])
const { t } = useI18n()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const saving = ref(false)
const error = ref('')

const isEdit = computed(() => !!props.template?.id)
const title = computed(() =>
  isEdit.value
    ? t('alert_matrix.templates.editor.edit_title')
    : t('alert_matrix.templates.editor.create_title')
)

const form = ref(blankForm())

function blankForm() {
  return { name: '', description: '', check_type: props.defaultCheckType, rows: [] }
}

watch(() => props.modelValue, (v) => {
  if (v) {
    form.value = props.template
      ? {
          name: props.template.name,
          description: props.template.description ?? '',
          check_type: props.template.check_type,
          rows: JSON.parse(JSON.stringify(props.template.rows ?? [])),
        }
      : blankForm()
    error.value = ''
  }
})

const availableConditions = computed(() => CONDITIONS_BY_TYPE[form.value.check_type] ?? [])

function conditionOptions(current) {
  const used = new Set(form.value.rows.map(r => r.condition))
  return availableConditions.value.filter(c => c === current || !used.has(c))
}

function needsThreshold(cond) {
  return isThresholdCondition(cond)
}

function addRow() {
  const next = availableConditions.value.find(c => !form.value.rows.some(r => r.condition === c))
  if (!next) return
  form.value.rows.push({ condition: next, min_duration_seconds: 0 })
}

function removeRow(idx) {
  form.value.rows.splice(idx, 1)
}

function close() {
  open.value = false
}

async function submit() {
  error.value = ''
  saving.value = true
  try {
    if (props.template?.is_system) {
      error.value = t('alert_matrix.templates.editor.system_readonly')
      return
    }
    const cleaned = form.value.rows.map(r => {
      const out = {}
      for (const [k, v] of Object.entries(r)) {
        if (v !== null && v !== '' && v !== undefined) out[k] = v
      }
      return out
    })
    if (isEdit.value) {
      await api.patch(`/alerts/matrix-templates/${props.template.id}`, {
        name: form.value.name,
        description: form.value.description || null,
        rows: cleaned,
      })
    } else {
      await api.post('/alerts/matrix-templates', {
        name: form.value.name,
        description: form.value.description || null,
        check_type: form.value.check_type,
        rows: cleaned,
      })
    }
    emit('saved')
    close()
  } catch (e) {
    error.value = e?.response?.data?.detail ?? String(e)
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!confirm(t('alert_matrix.templates.editor.confirm_delete'))) return
  saving.value = true
  try {
    await api.delete(`/alerts/matrix-templates/${props.template.id}`)
    emit('saved')
    close()
  } catch (e) {
    error.value = e?.response?.data?.detail ?? String(e)
  } finally {
    saving.value = false
  }
}
</script>
