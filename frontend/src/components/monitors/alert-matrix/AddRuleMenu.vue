<template>
  <div>
    <button
      type="button"
      @click="openModal"
      :disabled="!availableOptions.length"
      class="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-dashed border-gray-700 text-sm text-gray-400 hover:text-gray-200 hover:border-gray-500 disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <Plus :size="14" />
      <span>{{ t('alert_matrix.add_rule') }}</span>
    </button>

    <BaseModal v-model="open" :title="t('alert_matrix.add_rule')" size="md">
      <div class="space-y-3">
        <p class="text-xs text-gray-500">{{ t('alert_matrix.add_hint') }}</p>

        <div class="space-y-1 max-h-96 overflow-y-auto -mx-1 px-1">
          <div
            v-for="cond in availableOptions"
            :key="cond"
            class="rounded-lg border transition-colors"
            :class="selected.has(cond)
              ? 'border-blue-500/60 bg-blue-500/10'
              : 'border-gray-800 hover:border-gray-700'"
          >
            <button
              type="button"
              @click="toggleOne(cond)"
              class="w-full flex items-start gap-3 px-3 py-2.5 text-left"
            >
              <div
                class="mt-0.5 w-4 h-4 rounded flex items-center justify-center border shrink-0"
                :class="selected.has(cond)
                  ? 'border-blue-400 bg-blue-500 text-white'
                  : 'border-gray-600'"
              >
                <Check v-if="selected.has(cond)" :size="12" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="text-xs font-mono text-gray-200">{{ cond }}</div>
                <div class="text-[11px] text-gray-500 mt-0.5">
                  {{ t('alert_matrix.conditions.' + cond) }}
                </div>
              </div>
            </button>
            <details class="px-3 pb-2 -mt-1" @click.stop>
              <summary class="cursor-pointer text-[11px] text-blue-400 hover:text-blue-300 select-none inline-flex items-center gap-1 pl-7">
                <Info :size="11" />
                <span>{{ t('alert_matrix.help_title') }}</span>
              </summary>
              <p class="mt-2 ml-7 pl-3 pr-1 text-[11px] leading-relaxed text-gray-400 border-l-2 border-blue-900/50">
                {{ t('alert_matrix.help.' + cond) }}
              </p>
            </details>
          </div>
        </div>
      </div>

      <template #footer>
        <button type="button" @click="selectAll" class="btn-ghost text-xs">
          {{ allSelected ? t('alert_matrix.select_none') : t('alert_matrix.select_all') }}
        </button>
        <div class="flex-1" />
        <button type="button" @click="close" class="btn-ghost text-xs">
          {{ t('common.cancel') }}
        </button>
        <button
          type="button"
          @click="confirm"
          :disabled="!selected.size"
          class="btn-primary text-xs disabled:opacity-40"
        >
          {{ t('alert_matrix.add_selected') }}
          <span v-if="selected.size" class="ml-1 opacity-80">({{ selected.size }})</span>
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus, Check, Info } from 'lucide-vue-next'
import BaseModal from '../../BaseModal.vue'

const props = defineProps({
  available: { type: Array, required: true },
  used: { type: Array, required: true },
})
const emit = defineEmits(['add'])
const { t } = useI18n()

const open = ref(false)
const selected = ref(new Set())

const availableOptions = computed(() => props.available.filter(c => !props.used.includes(c)))
const allSelected = computed(
  () => availableOptions.value.length > 0 && selected.value.size === availableOptions.value.length
)

function openModal() {
  selected.value = new Set()
  open.value = true
}

function close() {
  open.value = false
}

function toggleOne(cond) {
  const next = new Set(selected.value)
  if (next.has(cond)) next.delete(cond)
  else next.add(cond)
  selected.value = next
}

function selectAll() {
  if (allSelected.value) selected.value = new Set()
  else selected.value = new Set(availableOptions.value)
}

function confirm() {
  for (const cond of selected.value) emit('add', cond)
  close()
}
</script>
