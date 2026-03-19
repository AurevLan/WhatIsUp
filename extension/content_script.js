/**
 * WhatIsUp Recorder — content script.
 *
 * Injected into every page. Activates event listeners only while recording.
 * Sends captured interactions to background.js via chrome.runtime.sendMessage.
 */

'use strict'

let _active = false
let _pwCount = 0

// Expose debug state on window for console diagnostics
Object.defineProperty(window, '__whatisup_recorder', {
  get: () => ({ active: _active, loaded: true }),
})

// ---------------------------------------------------------------------------
// Listen for commands from background.js
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'RECORDING_STARTED') {
    _active = true
    _pwCount = 0
    _attachListeners()
    console.debug('[WhatIsUp] recording started — listeners attached')
  } else if (msg.type === 'RECORDING_STOPPED') {
    _active = false
    _detachListeners()
    console.debug('[WhatIsUp] recording stopped')
  }
})

// ---------------------------------------------------------------------------
// Selector generation
// ---------------------------------------------------------------------------

/**
 * Build a CSS selector that is as stable as possible.
 * Priority: data-testid > id > aria-label > name attr > CSS path (fallback).
 */
function _selector(el) {
  if (!el || el === document.body) return 'body'

  if (el.dataset?.testid) return `[data-testid="${_esc(el.dataset.testid)}"]`
  if (el.id) return `#${CSS.escape(el.id)}`
  if (el.getAttribute('aria-label'))
    return `${el.tagName.toLowerCase()}[aria-label="${_esc(el.getAttribute('aria-label'))}"]`
  if (el.name) return `${el.tagName.toLowerCase()}[name="${_esc(el.name)}"]`

  // Fallback: walk up DOM and build a short nth-child path (max 4 levels)
  const parts = []
  let node = el
  for (let i = 0; i < 4 && node && node !== document.body; i++) {
    const tag = node.tagName.toLowerCase()
    const parent = node.parentElement
    if (!parent) break
    const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName)
    const nth = siblings.indexOf(node) + 1
    parts.unshift(siblings.length > 1 ? `${tag}:nth-of-type(${nth})` : tag)
    node = parent
  }
  return parts.join(' > ') || el.tagName.toLowerCase()
}

function _esc(str) {
  return str.replace(/"/g, '\\"')
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function _onClick(e) {
  if (!_active) return
  const el = e.target
  const tag = el.tagName.toLowerCase()

  // Skip inputs — handled by _onFill / _onSelect
  if (['input', 'textarea', 'select'].includes(tag)) return

  const sel = _selector(el)
  const label = el.innerText?.trim().slice(0, 60) || el.getAttribute('aria-label') || sel

  _addStep({
    type: 'click',
    label: `Click "${label}"`,
    params: { selector: sel },
  })
}

// Debounced fill/type handler — fires 600ms after the user stops typing
const _fillDebounceMap = new WeakMap()
function _onInput(e) {
  if (!_active) return
  const el = e.target
  const tag = el.tagName.toLowerCase()
  const isContentEditable = el.isContentEditable && tag !== 'input' && tag !== 'textarea'

  if (!['input', 'textarea'].includes(tag) && !isContentEditable) return
  if (el.type === 'hidden') return

  // Password fields: store value as a secret variable, use {{password_N}} placeholder
  if (el.type === 'password') {
    const existing = _fillDebounceMap.get(el)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      const sel = _selector(el)
      const value = el.value
      if (!value) return
      _pwCount += 1
      const varName = `password_${_pwCount}`
      chrome.runtime.sendMessage({ type: 'ADD_SECRET_VAR', name: varName, value }).catch(() => {})
      _addStep({
        type: 'fill',
        label: `Fill password field "${el.name || sel}"`,
        params: { selector: sel, value: `{{${varName}}}` },
      })
    }, 600)
    _fillDebounceMap.set(el, timer)
    return
  }

  const existing = _fillDebounceMap.get(el)
  if (existing) clearTimeout(existing)

  if (isContentEditable) {
    // contenteditable elements (rich-text editors) → type step
    const timer = setTimeout(() => {
      const sel = _selector(el)
      const text = (el.textContent || el.innerText || '').trim()
      chrome.runtime.sendMessage({ type: 'GET_STATE' }).then(({ steps }) => {
        const lastSameIdx = steps.findLastIndex(
          (s) => s.type === 'type' && s.params.selector === sel,
        )
        if (lastSameIdx !== -1) {
          chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: lastSameIdx })
        }
        _addStep({
          type: 'type',
          label: `Type "${text.slice(0, 40)}" in "${sel}"`,
          params: { selector: sel, text },
        })
      })
    }, 600)
    _fillDebounceMap.set(el, timer)
    return
  }

  const timer = setTimeout(() => {
    const sel = _selector(el)
    const value = el.value

    // Remove previous fill step for the same selector
    chrome.runtime.sendMessage({ type: 'GET_STATE' }).then(({ steps }) => {
      // Replace last fill step for same selector if present
      const lastSameIdx = steps.findLastIndex(
        (s) => s.type === 'fill' && s.params.selector === sel,
      )
      if (lastSameIdx !== -1) {
        chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: lastSameIdx })
      }
      _addStep({
        type: 'fill',
        label: `Fill "${el.name || el.placeholder || sel}" with "${value.slice(0, 40)}"`,
        params: { selector: sel, value },
      })
    })
  }, 600)

  _fillDebounceMap.set(el, timer)
}

// Tab key handler — captures Tab navigation as a press step
function _onKeydown(e) {
  if (!_active) return
  if (e.key !== 'Tab') return

  const el = document.activeElement
  if (!el || el === document.body || el === document.documentElement) return

  const sel = _selector(el)
  _addStep({
    type: 'press',
    label: `Press Tab on "${sel}"`,
    params: { selector: sel, key: 'Tab' },
  })
}

function _onSelect(e) {
  if (!_active) return
  const el = e.target
  if (el.tagName.toLowerCase() !== 'select') return

  const sel = _selector(el)
  const value = el.value

  _addStep({
    type: 'select',
    label: `Select "${value}" in "${el.name || sel}"`,
    params: { selector: sel, value },
  })
}

function _onSubmit(e) {
  if (!_active) return
  const sel = _selector(e.target)
  _addStep({
    type: 'click',
    label: `Submit form "${sel}"`,
    params: { selector: `${sel} [type="submit"]` },
  })
}

// ---------------------------------------------------------------------------
// Attach / detach
// ---------------------------------------------------------------------------

function _attachListeners() {
  document.addEventListener('click', _onClick, { capture: true, passive: true })
  document.addEventListener('input', _onInput, { capture: true, passive: true })
  document.addEventListener('change', _onSelect, { capture: true, passive: true })
  document.addEventListener('submit', _onSubmit, { capture: true, passive: true })
  document.addEventListener('keydown', _onKeydown, { capture: true, passive: true })
}

function _detachListeners() {
  document.removeEventListener('click', _onClick, { capture: true })
  document.removeEventListener('input', _onInput, { capture: true })
  document.removeEventListener('change', _onSelect, { capture: true })
  document.removeEventListener('submit', _onSubmit, { capture: true })
  document.removeEventListener('keydown', _onKeydown, { capture: true })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _addStep(step) {
  chrome.runtime.sendMessage({ type: 'ADD_STEP', step }).catch(() => {})
}
