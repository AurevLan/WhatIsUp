<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span
      v-for="tag in modelValue"
      :key="tag.id"
      class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-full border"
      :style="tag.color ? `border-color:${tag.color}80; background:${tag.color}20; color:${tag.color}` : ''"
      :class="!tag.color ? 'border-gray-700 text-gray-300 bg-gray-800/40' : ''"
    >
      {{ tag.name }}
      <button
        v-if="editable"
        type="button"
        @click="remove(tag)"
        class="text-xs opacity-60 hover:opacity-100"
        :title="t('tags.remove')"
      >✕</button>
    </span>

    <div v-if="editable" class="relative">
      <button
        v-if="!adding"
        type="button"
        @click="startAdd"
        class="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-full border border-dashed border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-500"
      >
        + {{ t('tags.add') }}
      </button>
      <div v-else class="inline-flex items-center gap-1">
        <input
          ref="inputRef"
          v-model="draft"
          @keydown.enter.prevent="commit"
          @keydown.escape="cancel"
          @blur="onBlur"
          :placeholder="t('tags.placeholder')"
          list="all-tags-list"
          class="input py-0.5 text-xs w-36"
        />
        <datalist id="all-tags-list">
          <option v-for="t in allTags" :key="t.id" :value="t.name" />
        </datalist>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../../api/client'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  editable: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const adding = ref(false)
const draft = ref('')
const inputRef = ref(null)
const allTags = ref([])

async function loadAllTags() {
  try {
    const { data } = await api.get('/tags/')
    allTags.value = data
  } catch {}
}

async function startAdd() {
  adding.value = true
  if (!allTags.value.length) await loadAllTags()
  await nextTick()
  inputRef.value?.focus()
}

function cancel() {
  draft.value = ''
  adding.value = false
}

function onBlur() {
  setTimeout(() => { if (adding.value && !draft.value) cancel() }, 150)
}

async function commit() {
  const name = draft.value.trim()
  if (!name) return cancel()
  if (props.modelValue.some(t => t.name === name)) return cancel()

  let tag = allTags.value.find(t => t.name === name)
  if (!tag) {
    const { data } = await api.post('/tags/', { name })
    tag = data
    allTags.value.push(tag)
  }
  emit('update:modelValue', [...props.modelValue, tag])
  draft.value = ''
  adding.value = false
}

function remove(tag) {
  emit('update:modelValue', props.modelValue.filter(t => t.id !== tag.id))
}

onMounted(loadAllTags)
</script>
