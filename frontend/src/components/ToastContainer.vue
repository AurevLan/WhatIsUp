<template>
  <Teleport to="body">
    <div style="position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          style="pointer-events:auto;display:flex;align-items:center;gap:10px;padding:12px 16px;border-radius:12px;min-width:260px;max-width:380px;font-size:13px;font-weight:500;line-height:1.4;box-shadow:0 8px 24px rgba(0,0,0,.5);cursor:pointer;backdrop-filter:blur(8px);"
          :style="toastStyle(toast.type)"
          @click="remove(toast.id)"
        >
          <span style="flex-shrink:0;font-size:16px;">{{ toastIcon(toast.type) }}</span>
          <span style="flex:1;">{{ toast.message }}</span>
          <span style="flex-shrink:0;opacity:.5;font-size:16px;line-height:1;">×</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../composables/useToast'

const { toasts, remove } = useToast()

function toastIcon(type) {
  return { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' }[type] ?? '●'
}

function toastStyle(type) {
  const cfg = {
    success: 'background:rgba(16,185,129,.15);border:1px solid rgba(16,185,129,.35);color:#34d399;',
    error:   'background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.35);color:#f87171;',
    warning: 'background:rgba(245,158,11,.15);border:1px solid rgba(245,158,11,.35);color:#fbbf24;',
    info:    'background:rgba(59,130,246,.15);border:1px solid rgba(59,130,246,.35);color:#60a5fa;',
  }
  return cfg[type] ?? cfg.info
}
</script>

<style scoped>
.toast-enter-active { transition: all .25s cubic-bezier(0.34,1.56,0.64,1); }
.toast-leave-active { transition: all .2s ease; }
.toast-enter-from   { opacity:0; transform:translateX(40px) scale(.95); }
.toast-leave-to     { opacity:0; transform:translateX(40px) scale(.95); }
</style>
