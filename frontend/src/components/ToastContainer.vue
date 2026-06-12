<template>
  <Teleport to="body">
    <div style="position:fixed;bottom:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none;">
      <TransitionGroup name="toast">
        <!-- A11Y-4: errors are assertive (role=alert), info/success/warning polite (role=status).
             Role sits on each toast so insertion into the DOM is what gets announced. -->
        <div
          v-for="toast in toasts"
          :key="toast.id"
          :role="toast.type === 'error' ? 'alert' : 'status'"
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
    success: 'background:color-mix(in srgb, var(--up) 15%, var(--bg-surface));border:1px solid color-mix(in srgb, var(--up) 35%, transparent);color:var(--up);',
    error:   'background:color-mix(in srgb, var(--down) 15%, var(--bg-surface));border:1px solid color-mix(in srgb, var(--down) 35%, transparent);color:var(--down);',
    warning: 'background:color-mix(in srgb, var(--warn) 15%, var(--bg-surface));border:1px solid color-mix(in srgb, var(--warn) 35%, transparent);color:var(--warn);',
    info:    'background:color-mix(in srgb, var(--accent) 15%, var(--bg-surface));border:1px solid color-mix(in srgb, var(--accent) 35%, transparent);color:var(--accent);',
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
