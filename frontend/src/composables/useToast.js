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

// Toast with a single action button (e.g. "Undo") — used for the deferred
// bulk-delete pattern (C4, bilan 2026-07): the caller defers its real side
// effect (an API call) until the toast expires, and cancels it entirely if
// the user clicks the action button in time.
//
// - Clicking the action button runs `onAction` and cancels `onExpire`.
// - Letting the toast run its course (including dismissing it early by
//   clicking elsewhere on the toast) still runs `onExpire` once the
//   duration elapses — only the action button skips it. This keeps "do
//   nothing" the safe default (the delete still happens, as advertised).
// Deliberately bypasses the activeByMessage dedup map: each action toast
// carries its own onAction/onExpire closures that must not be merged.
function addActionToast(message, { label, onAction, onExpire, type = 'info', duration = 6000 } = {}) {
  const id = ++nextId
  const timeoutId = setTimeout(() => {
    removeToast(id)
    onExpire?.()
  }, duration)
  toasts.push({
    id,
    message,
    type,
    action: label
      ? {
          label,
          run: () => {
            clearTimeout(timeoutId)
            removeToast(id)
            onAction?.()
          },
        }
      : null,
  })
  return id
}

export function useToast() {
  return {
    toasts,
    success: (msg) => addToast(msg, 'success', 3500),
    error:   (msg) => addToast(msg, 'error', 5000),
    info:    (msg) => addToast(msg, 'info', 3500),
    warning: (msg) => addToast(msg, 'warning', 4000),
    action:  addActionToast,
    remove:  removeToast,
  }
}
