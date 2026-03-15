/**
 * WhatIsUp Recorder — content script.
 *
 * Injected into every page. Activates event listeners only while recording.
 * Sends captured interactions to background.js via chrome.runtime.sendMessage.
 */

'use strict'

let _active = false

// ---------------------------------------------------------------------------
// Listen for commands from background.js
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'RECORDING_STARTED') {
    _active = true
    _attachListeners()
  } else if (msg.type === 'RECORDING_STOPPED') {
    _active = false
    _detachListeners()
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

// Debounced fill handler — fires 600ms after the user stops typing
const _fillDebounceMap = new WeakMap()
function _onInput(e) {
  if (!_active) return
  const el = e.target
  if (!['input', 'textarea'].includes(el.tagName.toLowerCase())) return
  if (['password', 'hidden'].includes(el.type)) return

  const existing = _fillDebounceMap.get(el)
  if (existing) clearTimeout(existing)

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
}

function _detachListeners() {
  document.removeEventListener('click', _onClick, { capture: true })
  document.removeEventListener('input', _onInput, { capture: true })
  document.removeEventListener('change', _onSelect, { capture: true })
  document.removeEventListener('submit', _onSubmit, { capture: true })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _addStep(step) {
  chrome.runtime.sendMessage({ type: 'ADD_STEP', step }).catch(() => {})
}
