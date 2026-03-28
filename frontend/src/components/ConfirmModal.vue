<template>
  <BaseModal :model-value="confirmState.visible" size="sm" @close="answer(false)">
    <h3 class="modal-title">{{ confirmState.title }}</h3>
    <p v-if="confirmState.message" class="modal-text">{{ confirmState.message }}</p>
    <div class="flex gap-2.5">
      <button @click="answer(false)" class="btn-secondary flex-1">
        Annuler
      </button>
      <button @click="answer(true)" :class="confirmState.danger ? 'btn-danger' : 'btn-primary'" class="flex-1">
        {{ confirmState.confirmLabel }}
      </button>
    </div>
  </BaseModal>
</template>

<script setup>
import BaseModal from './BaseModal.vue'
import { useConfirm } from '../composables/useConfirm'
const { confirmState, answer } = useConfirm()
</script>
