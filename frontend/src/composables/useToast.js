import { reactive } from 'vue'

const toasts = reactive([])
let nextId = 0

function addToast(message, type = 'success', duration = 3500) {
  const id = ++nextId
  toasts.push({ id, message, type })
  setTimeout(() => removeToast(id), duration)
}

function removeToast(id) {
  const idx = toasts.findIndex(t => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
}

export function useToast() {
  return {
    toasts,
    success: (msg) => addToast(msg, 'success', 3500),
    error:   (msg) => addToast(msg, 'error', 5000),
    info:    (msg) => addToast(msg, 'info', 3500),
    warning: (msg) => addToast(msg, 'warning', 4000),
    remove:  removeToast,
  }
}
