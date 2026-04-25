import { onMounted, onUnmounted } from 'vue'

const SEQUENCE_TIMEOUT_MS = 900

function isTypingTarget(target) {
  if (!target) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

function normaliseKey(e) {
  const k = e.key
  if (!k) return ''
  if (k === ' ') return 'space'
  if (k.length === 1) return k.toLowerCase()
  return k.toLowerCase()
}

/**
 * Register global hotkeys. Each binding has a `keys` string:
 *   - `"?"`     → single key
 *   - `"g d"`   → sequence (press g then d within 900 ms)
 *   - `"mod+k"` → ctrl/cmd modifier + key (handled separately by AppLayout for Cmd+K already)
 *
 * Bindings are skipped while the user is typing in an input/textarea or while
 * any modifier other than the shift required for the literal symbol is held.
 *
 * Usage:
 *   useHotkeys([
 *     { keys: 'g d', run: () => router.push('/') },
 *     { keys: '?',   run: () => openCheatsheet() },
 *   ])
 */
export function useHotkeys(bindings) {
  let buffer = ''
  let timer = null

  function resetBuffer() {
    buffer = ''
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  function tryMatch() {
    for (const b of bindings) {
      if (!b || !b.keys) continue
      if (b.keys === buffer || b.keys === buffer.trim()) {
        b.run()
        resetBuffer()
        return true
      }
    }
    // Still possibly a prefix of a longer binding?
    const isPrefix = bindings.some(
      (b) => b && b.keys && b.keys.startsWith(buffer) && b.keys !== buffer,
    )
    if (!isPrefix) resetBuffer()
    return false
  }

  function onKeydown(e) {
    if (isTypingTarget(e.target)) return
    if (e.metaKey || e.ctrlKey || e.altKey) return

    const key = normaliseKey(e)
    if (!key || key === 'shift' || key === 'meta' || key === 'control' || key === 'alt') return

    // Single-key bindings short-circuit so '?' and '/' fire instantly.
    const single = bindings.find((b) => b && b.keys === key)
    if (single && !buffer) {
      e.preventDefault()
      single.run()
      return
    }

    buffer = buffer ? `${buffer} ${key}` : key
    if (timer) clearTimeout(timer)
    timer = setTimeout(resetBuffer, SEQUENCE_TIMEOUT_MS)

    if (tryMatch()) e.preventDefault()
  }

  onMounted(() => window.addEventListener('keydown', onKeydown))
  onUnmounted(() => {
    window.removeEventListener('keydown', onKeydown)
    resetBuffer()
  })

  return { _onKeydown: onKeydown, _resetBuffer: resetBuffer }
}

export const HOTKEYS_SEQUENCE_TIMEOUT_MS = SEQUENCE_TIMEOUT_MS
