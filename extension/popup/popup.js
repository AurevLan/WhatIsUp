'use strict'

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const recordBtn = document.getElementById('recordBtn')
const recordLabel = document.getElementById('recordLabel')
const clearBtn = document.getElementById('clearBtn')
const stepsList = document.getElementById('stepsList')
const emptyMsg = document.getElementById('emptyMsg')
const stepCount = document.getElementById('stepCount')
const sendPanel = document.getElementById('sendPanel')
const monitorName = document.getElementById('monitorName')
const sendBtn = document.getElementById('sendBtn')
const statusMsg = document.getElementById('statusMsg')
const settingsBtn = document.getElementById('settingsBtn')

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let recording = false
let steps = []

// ---------------------------------------------------------------------------
// Initialisation: fetch current state from background
// ---------------------------------------------------------------------------

chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
  if (chrome.runtime.lastError) return
  recording = state.recording
  steps = state.steps ?? []
  _render()
})

// Live updates pushed from background while popup is open
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STEPS_UPDATED') {
    steps = msg.steps
    _render()
  }
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

recordBtn.addEventListener('click', async () => {
  if (!recording) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    chrome.runtime.sendMessage({ type: 'START_RECORDING', tabId: tab?.id })
    recording = true
  } else {
    chrome.runtime.sendMessage({ type: 'STOP_RECORDING' }, (res) => {
      if (res) steps = res.steps
      recording = false
      _render()
    })
    recording = false
  }
  _render()
})

clearBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'CLEAR_STEPS' })
  steps = []
  _render()
})

sendBtn.addEventListener('click', async () => {
  const name = monitorName.value.trim()
  if (!name) {
    monitorName.focus()
    return
  }

  sendBtn.disabled = true
  sendBtn.textContent = 'Sending…'
  _hideStatus()

  chrome.runtime.sendMessage(
    { type: 'SEND_TO_WHATISUP', monitorName: name, steps },
    (res) => {
      sendBtn.disabled = false
      sendBtn.textContent = 'Send to WhatIsUp'

      if (res.ok) {
        _showStatus(`✓ Monitor "${name}" created successfully!`, true)
      } else {
        _showStatus(`✗ ${res.error}`, false)
      }
    },
  )
})

settingsBtn.addEventListener('click', () => {
  chrome.runtime.openOptionsPage()
})

// Remove individual step via event delegation
stepsList.addEventListener('click', (e) => {
  const btn = e.target.closest('.step-remove')
  if (!btn) return
  const idx = parseInt(btn.dataset.index, 10)
  chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: idx }, (res) => {
    if (res?.steps) steps = res.steps
    _render()
  })
})

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const STEP_ICONS = {
  navigate: '🌐',
  click: '👆',
  fill: '✏️',
  press: '⌨️',
  type: '⌨️',
  select: '🔽',
  submit: '📤',
  wait_element: '⏳',
  wait_time: '⏱️',
  assert_text: '🔍',
  assert_visible: '👁️',
  assert_url: '🔗',
  screenshot: '📸',
  hover: '🖱️',
  scroll: '↕️',
  extract: '📋',
}

function _createStepEl(step, index) {
  const el = document.createElement('div')
  el.className = 'step-item'

  const iconEl = document.createElement('span')
  iconEl.className = 'step-icon'
  iconEl.textContent = STEP_ICONS[step.type] ?? '▶️'

  const labelEl = document.createElement('span')
  labelEl.className = 'step-label'
  labelEl.textContent = step.label ?? step.type

  const removeBtn = document.createElement('button')
  removeBtn.className = 'step-remove'
  removeBtn.dataset.index = index
  removeBtn.title = 'Remove'
  removeBtn.textContent = '✕'

  el.appendChild(iconEl)
  el.appendChild(labelEl)
  el.appendChild(removeBtn)
  return el
}

function _render() {
  // Record button
  if (recording) {
    recordBtn.classList.add('recording')
    recordLabel.textContent = 'Stop'
  } else {
    recordBtn.classList.remove('recording')
    recordLabel.textContent = 'Record'
  }

  // Step count & clear
  stepCount.textContent = steps.length
  clearBtn.disabled = steps.length === 0

  if (steps.length === 0) {
    emptyMsg.style.display = 'block'
    stepsList.querySelectorAll('.step-item').forEach((el) => el.remove())
    sendPanel.style.display = 'none'
    return
  }

  emptyMsg.style.display = 'none'
  sendPanel.style.display = 'block'

  const existing = Array.from(stepsList.querySelectorAll('.step-item'))

  // Remove excess elements
  while (existing.length > steps.length) {
    existing.pop().remove()
  }

  steps.forEach((step, i) => {
    const icon = STEP_ICONS[step.type] ?? '▶️'
    if (i < existing.length) {
      // Update in-place with textContent only (safe)
      existing[i].querySelector('.step-icon').textContent = icon
      existing[i].querySelector('.step-label').textContent = step.label ?? step.type
      existing[i].querySelector('.step-remove').dataset.index = i
    } else {
      stepsList.appendChild(_createStepEl(step, i))
    }
  })
}

function _showStatus(text, ok) {
  statusMsg.textContent = text
  statusMsg.className = `status-msg ${ok ? 'status-ok' : 'status-err'}`
  statusMsg.style.display = 'block'
}

function _hideStatus() {
  statusMsg.style.display = 'none'
}
