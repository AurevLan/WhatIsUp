/**
 * WhatIsUp Recorder — content script (v2).
 *
 * Injected into every page (including iframes via all_frames: true).
 * Captures: click, fill, select, submit, keydown, hover, scroll, drag&drop, file upload.
 * Generates multi-selector fallbacks and timing hints.
 */

'use strict'

// Guard against duplicate injection (programmatic re-inject on navigation)
if (window.__whatisup_recorder?.loaded) {
  // Already injected — skip re-initialization
} else {

let _active = false
let _pwCount = 0
let _lastScrollY = 0
let _lastScrollX = 0

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
    _lastScrollY = window.scrollY
    _lastScrollX = window.scrollX
    _attachListeners()
    console.debug('[WhatIsUp] recording started — listeners attached')
  } else if (msg.type === 'RECORDING_STOPPED') {
    _active = false
    _detachListeners()
    console.debug('[WhatIsUp] recording stopped')
  }
})

// ---------------------------------------------------------------------------
// Selector generation — multi-selector with CSS, XPath, text fallback
// ---------------------------------------------------------------------------

/**
 * Build a multi-selector object { css, xpath, text } for an element.
 * The `css` key is the primary selector (backward-compatible).
 */
function _selectors(el) {
  if (!el || el === document.body) return { css: 'body', xpath: '//body', text: null }

  const css = _cssSelector(el)
  const xpath = _xpathSelector(el)
  const text = _textSelector(el)

  return { css, xpath, text }
}

/** CSS selector — same priority as v1: data-testid > id > aria-label > name > nth-child path */
function _cssSelector(el) {
  if (!el || el === document.body) return 'body'
  if (el.dataset?.testid) return `[data-testid="${_escCSS(el.dataset.testid)}"]`
  if (el.id) return `#${CSS.escape(el.id)}`
  if (el.getAttribute('aria-label'))
    return `${el.tagName.toLowerCase()}[aria-label="${_escCSS(el.getAttribute('aria-label'))}"]`
  if (el.name) return `${el.tagName.toLowerCase()}[name="${_escCSS(el.name)}"]`

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

/** XPath selector — simple: prefer id, then text content */
function _xpathSelector(el) {
  if (!el || el === document.body) return '//body'
  const tag = el.tagName.toLowerCase()
  if (el.id) return `//${tag}[@id="${_escXPath(el.id)}"]`
  const text = (el.textContent || '').trim().slice(0, 40)
  if (text && !el.children.length) return `//${tag}[text()="${_escXPath(text)}"]`
  if (el.getAttribute('aria-label')) return `//${tag}[@aria-label="${_escXPath(el.getAttribute('aria-label'))}"]`
  if (el.name) return `//${tag}[@name="${_escXPath(el.name)}"]`
  return `//${tag}`
}

/** Text-based selector for Playwright text= locator */
function _textSelector(el) {
  if (!el) return null
  const text = (el.textContent || el.innerText || '').trim()
  if (text && text.length < 80 && !el.children.length) return text
  return null
}

/** Escape a string for use inside a CSS attribute selector: [attr="value"] */
function _escCSS(str) {
  return CSS.escape(str)
}

/** Escape a string for use inside an XPath expression: @attr="value" */
function _escXPath(str) {
  // If the string contains both quotes, use concat()
  if (str.includes('"') && str.includes("'")) {
    return 'concat(' + str.split('"').map((s) => `"${s}"`).join(',\'"\',' ) + ')'
  }
  if (str.includes('"')) return `'${str}'`
  return str.replaceAll('\\', '\\\\').replaceAll('"', '\\"')
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function _onClick(e) {
  if (!_active) return
  const el = e.target
  const tag = el.tagName.toLowerCase()
  if (['input', 'textarea', 'select'].includes(tag)) return

  const sels = _selectors(el)
  const label = el.innerText?.trim().slice(0, 60) || el.getAttribute('aria-label') || sels.css

  _addStep({
    type: 'click',
    label: `Click "${label}"`,
    params: { selector: sels.css, selectors: sels },
  })
}

// Debounced fill/type handler
const _fillDebounceMap = new WeakMap()
function _onInput(e) {
  if (!_active) return
  const el = e.target
  const tag = el.tagName.toLowerCase()
  const isContentEditable = el.isContentEditable && tag !== 'input' && tag !== 'textarea'

  if (!['input', 'textarea'].includes(tag) && !isContentEditable) return
  if (el.type === 'hidden') return

  if (el.type === 'password') {
    const existing = _fillDebounceMap.get(el)
    if (existing) clearTimeout(existing)
    const timer = setTimeout(() => {
      const sels = _selectors(el)
      const value = el.value
      if (!value) return
      _pwCount += 1
      const varName = `password_${_pwCount}`
      chrome.runtime.sendMessage({ type: 'ADD_SECRET_VAR', name: varName, value }).catch(() => {})
      _addStep({
        type: 'fill',
        label: `Fill password field "${el.name || sels.css}"`,
        params: { selector: sels.css, selectors: sels, value: `{{${varName}}}` },
      })
    }, 600)
    _fillDebounceMap.set(el, timer)
    return
  }

  const existing = _fillDebounceMap.get(el)
  if (existing) clearTimeout(existing)

  if (isContentEditable) {
    const timer = setTimeout(() => {
      const sels = _selectors(el)
      const text = (el.textContent || el.innerText || '').trim()
      chrome.runtime.sendMessage({ type: 'GET_STATE' }).then(({ steps }) => {
        const lastSameIdx = steps.findLastIndex(
          (s) => s.type === 'type' && s.params.selector === sels.css,
        )
        if (lastSameIdx !== -1) {
          chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: lastSameIdx })
        }
        _addStep({
          type: 'type',
          label: `Type "${text.slice(0, 40)}" in "${sels.css}"`,
          params: { selector: sels.css, selectors: sels, text },
        })
      })
    }, 600)
    _fillDebounceMap.set(el, timer)
    return
  }

  const timer = setTimeout(() => {
    const sels = _selectors(el)
    const value = el.value

    chrome.runtime.sendMessage({ type: 'GET_STATE' }).then(({ steps }) => {
      const lastSameIdx = steps.findLastIndex(
        (s) => s.type === 'fill' && s.params.selector === sels.css,
      )
      if (lastSameIdx !== -1) {
        chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: lastSameIdx })
      }
      _addStep({
        type: 'fill',
        label: `Fill "${el.name || el.placeholder || sels.css}" with "${value.slice(0, 40)}"`,
        params: { selector: sels.css, selectors: sels, value },
      })
    })
  }, 600)

  _fillDebounceMap.set(el, timer)
}

function _onKeydown(e) {
  if (!_active) return
  if (e.key !== 'Tab') return
  const el = document.activeElement
  if (!el || el === document.body || el === document.documentElement) return
  const sels = _selectors(el)
  _addStep({
    type: 'press',
    label: `Press Tab on "${sels.css}"`,
    params: { selector: sels.css, selectors: sels, key: 'Tab' },
  })
}

function _onSelect(e) {
  if (!_active) return
  const el = e.target
  if (el.tagName.toLowerCase() !== 'select') return
  const sels = _selectors(el)
  const value = el.value
  _addStep({
    type: 'select',
    label: `Select "${value}" in "${el.name || sels.css}"`,
    params: { selector: sels.css, selectors: sels, value },
  })
}

function _onSubmit(e) {
  if (!_active) return
  const sels = _selectors(e.target)
  _addStep({
    type: 'click',
    label: `Submit form "${sels.css}"`,
    params: { selector: `${sels.css} [type="submit"]`, selectors: sels },
  })
}

// ---------------------------------------------------------------------------
// NEW: Hover capture (menus, dropdowns)
// ---------------------------------------------------------------------------

const HOVER_SELECTORS = [
  '[role="menuitem"]', '[role="menu"]', '.dropdown-toggle', '.dropdown',
  'nav li', '[aria-haspopup]', '.nav-item',
]

function _onMouseEnter(e) {
  if (!_active) return
  const el = e.target
  const matches = HOVER_SELECTORS.some((s) => {
    try { return el.matches(s) } catch { return false }
  })
  if (!matches) return
  const sels = _selectors(el)
  const label = el.innerText?.trim().slice(0, 40) || sels.css
  _addStep({
    type: 'hover',
    label: `Hover "${label}"`,
    params: { selector: sels.css, selectors: sels },
  })
}

// ---------------------------------------------------------------------------
// NEW: Scroll capture (debounced, significant only)
// ---------------------------------------------------------------------------

let _scrollTimer = null
function _onScroll() {
  if (!_active) return
  if (_scrollTimer) clearTimeout(_scrollTimer)
  _scrollTimer = setTimeout(() => {
    const dx = Math.abs(window.scrollX - _lastScrollX)
    const dy = Math.abs(window.scrollY - _lastScrollY)
    if (dx < 200 && dy < 200) return
    _lastScrollX = window.scrollX
    _lastScrollY = window.scrollY
    _addStep({
      type: 'scroll',
      label: `Scroll to (${window.scrollX}, ${window.scrollY})`,
      params: { selector: 'window', x: window.scrollX, y: window.scrollY },
    })
  }, 1000)
}

// ---------------------------------------------------------------------------
// NEW: Drag & drop capture
// ---------------------------------------------------------------------------

let _dragSource = null
function _onDragStart(e) {
  if (!_active) return
  _dragSource = e.target
}

function _onDrop(e) {
  if (!_active || !_dragSource) return
  const sourceSels = _selectors(_dragSource)
  const targetSels = _selectors(e.target)
  _addStep({
    type: 'drag',
    label: `Drag from "${sourceSels.css}" to "${targetSels.css}"`,
    params: {
      sourceSelector: sourceSels.css,
      targetSelector: targetSels.css,
      sourceSelectors: sourceSels,
      targetSelectors: targetSels,
    },
  })
  _dragSource = null
}

// ---------------------------------------------------------------------------
// NEW: File upload capture
// ---------------------------------------------------------------------------

function _onFileChange(e) {
  if (!_active) return
  const el = e.target
  if (el.tagName.toLowerCase() !== 'input' || el.type !== 'file') return
  const files = Array.from(el.files || [])
  if (!files.length) return
  const sels = _selectors(el)
  _addStep({
    type: 'upload',
    label: `Upload "${files.map((f) => f.name).join(', ')}" to "${sels.css}"`,
    params: {
      selector: sels.css,
      selectors: sels,
      fileNames: files.map((f) => f.name),
    },
  })
}

// ---------------------------------------------------------------------------
// Attach / detach
// ---------------------------------------------------------------------------

function _attachListeners() {
  document.addEventListener('click', _onClick, { capture: true, passive: true })
  document.addEventListener('input', _onInput, { capture: true, passive: true })
  document.addEventListener('change', _onSelect, { capture: true, passive: true })
  document.addEventListener('change', _onFileChange, { capture: true, passive: true })
  document.addEventListener('submit', _onSubmit, { capture: true, passive: true })
  document.addEventListener('keydown', _onKeydown, { capture: true, passive: true })
  document.addEventListener('mouseenter', _onMouseEnter, { capture: true, passive: true })
  document.addEventListener('scroll', _onScroll, { capture: true, passive: true })
  document.addEventListener('dragstart', _onDragStart, { capture: true, passive: true })
  document.addEventListener('drop', _onDrop, { capture: true, passive: true })
}

function _detachListeners() {
  document.removeEventListener('click', _onClick, { capture: true })
  document.removeEventListener('input', _onInput, { capture: true })
  document.removeEventListener('change', _onSelect, { capture: true })
  document.removeEventListener('change', _onFileChange, { capture: true })
  document.removeEventListener('submit', _onSubmit, { capture: true })
  document.removeEventListener('keydown', _onKeydown, { capture: true })
  document.removeEventListener('mouseenter', _onMouseEnter, { capture: true })
  document.removeEventListener('scroll', _onScroll, { capture: true })
  document.removeEventListener('dragstart', _onDragStart, { capture: true })
  document.removeEventListener('drop', _onDrop, { capture: true })
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _addStep(step) {
  step.params.timestamp = Date.now()
  chrome.runtime.sendMessage({ type: 'ADD_STEP', step }).catch(() => {})
}

} // end guard against duplicate injection
