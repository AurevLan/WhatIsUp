import { reactive } from 'vue'

const toasts = reactive([])
let nextId = 0

// message → { id, timeoutId } — lets addToast() refresh an already-visible
// toast's timer instead of stacking a duplicate on top of it (e.g. repeated
// polling failures that all resolve to the same generic error message).
const activeByMessage = new Map()

function addToast(message, type = 'success', duration = 3500) {
  const existing = activeByMessage.get(message)
  if (existing && existing.type === type) {
    clearTimeout(existing.timeoutId)
    existing.timeoutId = setTimeout(() => removeToast(existing.id), duration)
    return
  }

  const id = ++nextId
  toasts.push({ id, message, type })
  const timeoutId = setTimeout(() => removeToast(id), duration)
  activeByMessage.set(message, { id, type, timeoutId })
}

function removeToast(id) {
  const idx = toasts.findIndex(t => t.id === id)
  if (idx !== -1) toasts.splice(idx, 1)
  for (const [message, entry] of activeByMessage) {
    if (entry.id === id) {
      activeByMessage.delete(message)
      break
    }
  }
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
