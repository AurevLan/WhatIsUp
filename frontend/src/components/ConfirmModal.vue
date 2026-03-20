<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="confirmState.visible"
        style="position:fixed;inset:0;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;z-index:9000;padding:16px;"
        @click.self="answer(false)"
      >
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:16px;width:100%;max-width:380px;padding:24px;box-shadow:0 24px 64px rgba(0,0,0,.7);">
          <h3 style="font-size:15px;font-weight:700;color:#f1f5f9;margin:0 0 8px;">{{ confirmState.title }}</h3>
          <p v-if="confirmState.message" style="font-size:13px;color:#64748b;margin:0 0 24px;line-height:1.5;">{{ confirmState.message }}</p>
          <div style="display:flex;gap:10px;">
            <button
              @click="answer(false)"
              style="flex:1;padding:9px 16px;border:1px solid #334155;border-radius:10px;background:transparent;color:#94a3b8;font-size:13px;font-weight:500;cursor:pointer;transition:all .15s;"
              onmouseenter="this.style.borderColor='#475569';this.style.color='#e2e8f0';"
              onmouseleave="this.style.borderColor='#334155';this.style.color='#94a3b8';"
            >
              Annuler
            </button>
            <button
              @click="answer(true)"
              :style="confirmState.danger
                ? 'flex:1;padding:9px 16px;border:1px solid #dc2626;border-radius:10px;background:#dc2626;color:white;font-size:13px;font-weight:600;cursor:pointer;transition:all .15s;'
                : 'flex:1;padding:9px 16px;border:1px solid #2563eb;border-radius:10px;background:#2563eb;color:white;font-size:13px;font-weight:600;cursor:pointer;transition:all .15s;'"
              onmouseenter="this.style.opacity='.9';"
              onmouseleave="this.style.opacity='1';"
            >
              {{ confirmState.confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { useConfirm } from '../composables/useConfirm'
const { confirmState, answer } = useConfirm()
</script>

<style scoped>
.modal-enter-active { transition: all .2s ease; }
.modal-leave-active { transition: all .15s ease; }
.modal-enter-from, .modal-leave-to { opacity:0; }
.modal-enter-from > div { transform: scale(.95) translateY(8px); }
.modal-leave-to > div   { transform: scale(.95) translateY(8px); }
</style>
