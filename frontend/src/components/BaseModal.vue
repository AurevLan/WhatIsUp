<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="modelValue" class="modal-overlay" @click.self="close">
        <div class="modal-panel" :class="[sizeClass]">
          <div v-if="title || $slots.header" class="flex items-center justify-between mb-5">
            <slot name="header">
              <h2 class="modal-title">{{ title }}</h2>
            </slot>
            <button @click="close" class="btn-ghost p-1 -mr-1" aria-label="Close">
              <X :size="16" />
            </button>
          </div>
          <p v-if="message" class="modal-text">{{ message }}</p>
          <slot />
          <div v-if="$slots.footer" class="flex gap-2.5 mt-6">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: { type: Boolean, default: true },
  title: { type: String, default: '' },
  message: { type: String, default: '' },
  size: { type: String, default: 'md' }, // sm | md | lg
})

const emit = defineEmits(['update:modelValue', 'close'])

const sizeClass = computed(() => {
  if (props.size === 'lg') return 'modal-panel-lg'
  if (props.size === 'sm') return 'max-w-xs'
  return ''
})

function close() {
  emit('update:modelValue', false)
  emit('close')
}
</script>

<style scoped>
.modal-enter-active { transition: opacity .2s ease; }
.modal-leave-active { transition: opacity .15s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }
.modal-enter-active .modal-panel { animation: modal-in .2s ease-out; }
.modal-leave-active .modal-panel { animation: modal-out .15s ease-in; }
@keyframes modal-in {
  from { opacity: 0; transform: scale(.95) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
@keyframes modal-out {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to   { opacity: 0; transform: scale(.95) translateY(8px); }
}
</style>
