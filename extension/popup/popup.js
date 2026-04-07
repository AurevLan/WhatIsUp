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
const tabBar = document.getElementById('tabBar')
const monitorName = document.getElementById('monitorName')
const sendBtn = document.getElementById('sendBtn')
const triggerBtn = document.getElementById('triggerBtn')
const statusMsg = document.getElementById('statusMsg')
const settingsBtn = document.getElementById('settingsBtn')
const monitorsBtn = document.getElementById('monitorsBtn')
const monitorPanel = document.getElementById('monitorPanel')
const assertBar = document.getElementById('assertBar')
const assertForm = document.getElementById('assertForm')
const assertFields = document.getElementById('assertFields')
const assertConfirm = document.getElementById('assertConfirm')
const assertCancel = document.getElementById('assertCancel')
const codeBlock = document.getElementById('codeBlock')
const copyCodeBtn = document.getElementById('copyCodeBtn')
const exportJsonBtn = document.getElementById('exportJsonBtn')
const exportPwBtn = document.getElementById('exportPwBtn')

const panels = {
  send: document.getElementById('panelSend'),
  preview: document.getElementById('panelPreview'),
  export: document.getElementById('panelExport'),
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let recording = false
let steps = []
let editingMonitorId = null
let activeTab = 'send'
let editingStepIndex = -1
let monitorPanelOpen = false
let pendingAssertType = null

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

chrome.runtime.sendMessage({ type: 'GET_STATE' }, (state) => {
  if (chrome.runtime.lastError) return
  recording = state.recording
  steps = state.steps ?? []
  editingMonitorId = state.editingMonitorId ?? null
  _render()
})

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'STEPS_UPDATED') {
    steps = msg.steps
    _render()
  }
})

// ---------------------------------------------------------------------------
// Record / Clear
// ---------------------------------------------------------------------------

recordBtn.addEventListener('click', async () => {
  if (!recording) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
    chrome.runtime.sendMessage({ type: 'START_RECORDING', tabId: tab?.id })
    recording = true
    editingMonitorId = null
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
  editingMonitorId = null
  editingStepIndex = -1
  _render()
})

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

tabBar.addEventListener('click', (e) => {
  const btn = e.target.closest('.tab-btn')
  if (!btn) return
  activeTab = btn.dataset.tab
  _renderTabs()
})

// ---------------------------------------------------------------------------
// Send / Update
// ---------------------------------------------------------------------------

sendBtn.addEventListener('click', async () => {
  const name = monitorName.value.trim()
  if (!name && !editingMonitorId) { monitorName.focus(); return }

  sendBtn.disabled = true
  sendBtn.textContent = 'Sending…'
  _hideStatus()

  chrome.runtime.sendMessage(
    { type: 'SEND_TO_WHATISUP', monitorName: name, steps },
    (res) => {
      sendBtn.disabled = false
      sendBtn.textContent = editingMonitorId ? 'Update Monitor' : 'Send to WhatIsUp'
      if (res?.ok) {
        const verb = res.updated ? 'updated' : 'created'
        _showStatus(`Monitor "${name}" ${verb} successfully!`, true)
      } else {
        _showStatus(res?.error || 'Unknown error', false)
      }
    },
  )
})

// ---------------------------------------------------------------------------
// Trigger check
// ---------------------------------------------------------------------------

triggerBtn.addEventListener('click', () => {
  if (!editingMonitorId) return
  triggerBtn.disabled = true
  triggerBtn.textContent = 'Running…'
  chrome.runtime.sendMessage({ type: 'TRIGGER_CHECK', monitorId: editingMonitorId }, (res) => {
    triggerBtn.disabled = false
    triggerBtn.textContent = 'Run test'
    if (res?.ok) _showStatus('Check queued!', true)
    else _showStatus(res?.error || 'Failed', false)
  })
})

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

settingsBtn.addEventListener('click', () => chrome.runtime.openOptionsPage())

// ---------------------------------------------------------------------------
// Monitor list
// ---------------------------------------------------------------------------

monitorsBtn.addEventListener('click', () => {
  monitorPanelOpen = !monitorPanelOpen
  if (monitorPanelOpen) _loadMonitorList()
  else monitorPanel.classList.add('hidden')
})

function _setMonitorPanelMessage(text, color) {
  monitorPanel.innerHTML = ''
  const div = document.createElement('div')
  div.style.cssText = `padding:8px;color:${color};font-size:12px`
  div.textContent = text
  monitorPanel.appendChild(div)
}

function _loadMonitorList() {
  monitorPanel.classList.remove('hidden')
  _setMonitorPanelMessage('Loading…', '#6b7280')

  chrome.runtime.sendMessage({ type: 'LIST_MONITORS' }, (res) => {
    if (!res?.ok) {
      _setMonitorPanelMessage(res?.error || 'Error', '#f87171')
      return
    }
    const monitors = res.monitors || []
    if (!monitors.length) {
      _setMonitorPanelMessage('No scenario monitors found.', '#6b7280')
      return
    }
    monitorPanel.innerHTML = ''
    monitors.forEach((m) => {
      const item = document.createElement('div')
      item.className = 'monitor-item'
      item.dataset.id = m.id

      const status = document.createElement('span')
      const s = (m.last_status || m.status || '').toLowerCase()
      status.className = `monitor-status ${s === 'up' ? 'up' : s === 'down' ? 'down' : 'unknown'}`

      const name = document.createElement('span')
      name.className = 'monitor-name'
      name.textContent = m.name

      item.appendChild(status)
      item.appendChild(name)
      item.addEventListener('click', () => _onLoadMonitor(m.id, m.name))
      monitorPanel.appendChild(item)
    })
  })
}

function _onLoadMonitor(monitorId, name) {
  chrome.runtime.sendMessage({ type: 'LOAD_MONITOR', monitorId }, (res) => {
    if (res?.ok) {
      steps = res.steps || []
      editingMonitorId = monitorId
      monitorName.value = name || ''
      monitorPanelOpen = false
      monitorPanel.classList.add('hidden')
      _render()
    }
  })
}

// ---------------------------------------------------------------------------
// Assertion toolbar
// ---------------------------------------------------------------------------

assertBar.addEventListener('click', (e) => {
  const btn = e.target.closest('.assert-btn')
  if (!btn) return
  const type = btn.dataset.assert

  if (type === 'screenshot') {
    const step = { type: 'screenshot', label: 'Take screenshot', params: { timestamp: Date.now() } }
    chrome.runtime.sendMessage({ type: 'ADD_STEP', step })
    steps.push(step)
    _render()
    return
  }

  pendingAssertType = type
  _showAssertForm(type)
})

function _showAssertForm(type) {
  const fields = {
    wait_element: [{ name: 'selector', label: 'CSS Selector', placeholder: '#login-btn' }],
    wait_time: [{ name: 'ms', label: 'Milliseconds', placeholder: '2000', inputType: 'number' }],
    assert_text: [
      { name: 'selector', label: 'CSS Selector', placeholder: '.message' },
      { name: 'text', label: 'Expected text', placeholder: 'Welcome' },
    ],
    assert_visible: [{ name: 'selector', label: 'CSS Selector', placeholder: '#dashboard' }],
    assert_url: [{ name: 'url', label: 'URL pattern', placeholder: 'https://example.com/dashboard' }],
  }

  const defs = fields[type] || []
  assertFields.innerHTML = ''
  defs.forEach((f) => {
    const lbl = document.createElement('label')
    lbl.textContent = f.label
    const inp = document.createElement('input')
    inp.name = f.name
    inp.placeholder = f.placeholder || ''
    inp.type = f.inputType || 'text'
    assertFields.appendChild(lbl)
    assertFields.appendChild(inp)
  })

  assertForm.classList.add('visible')
  const first = assertFields.querySelector('input')
  if (first) first.focus()
}

assertConfirm.addEventListener('click', () => {
  if (!pendingAssertType) return
  const inputs = assertFields.querySelectorAll('input')
  const params = { timestamp: Date.now() }
  inputs.forEach((inp) => {
    params[inp.name] = inp.type === 'number' ? Number(inp.value) : inp.value
  })

  const labels = {
    wait_element: `Wait for "${params.selector}"`,
    wait_time: `Wait ${params.ms}ms`,
    assert_text: `Assert "${params.text}" in "${params.selector}"`,
    assert_visible: `Assert "${params.selector}" is visible`,
    assert_url: `Assert URL "${params.url}"`,
  }

  const step = {
    type: pendingAssertType,
    label: labels[pendingAssertType] || pendingAssertType,
    params,
  }

  chrome.runtime.sendMessage({ type: 'ADD_STEP', step })
  steps.push(step)
  pendingAssertType = null
  assertForm.classList.remove('visible')
  _render()
})

assertCancel.addEventListener('click', () => {
  pendingAssertType = null
  assertForm.classList.remove('visible')
})

// ---------------------------------------------------------------------------
// Step removal (event delegation)
// ---------------------------------------------------------------------------

stepsList.addEventListener('click', (e) => {
  const removeBtn = e.target.closest('.step-remove')
  if (removeBtn) {
    const idx = parseInt(removeBtn.dataset.index, 10)
    chrome.runtime.sendMessage({ type: 'REMOVE_STEP', index: idx }, (res) => {
      if (res?.steps) steps = res.steps
      if (editingStepIndex === idx) editingStepIndex = -1
      _render()
    })
    return
  }

  const label = e.target.closest('.step-label')
  if (label) {
    const idx = parseInt(label.dataset.index, 10)
    editingStepIndex = editingStepIndex === idx ? -1 : idx
    _render()
  }
})

// ---------------------------------------------------------------------------
// Drag-to-reorder steps
// ---------------------------------------------------------------------------

let dragFromIndex = -1

stepsList.addEventListener('dragstart', (e) => {
  const item = e.target.closest('.step-item')
  if (!item) return
  dragFromIndex = parseInt(item.dataset.index, 10)
  item.classList.add('dragging')
  e.dataTransfer.effectAllowed = 'move'
})

stepsList.addEventListener('dragover', (e) => {
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  const item = e.target.closest('.step-item')
  if (item) item.classList.add('drag-over')
})

stepsList.addEventListener('dragleave', (e) => {
  const item = e.target.closest('.step-item')
  if (item) item.classList.remove('drag-over')
})

stepsList.addEventListener('drop', (e) => {
  e.preventDefault()
  const item = e.target.closest('.step-item')
  if (!item) return
  item.classList.remove('drag-over')
  const toIndex = parseInt(item.dataset.index, 10)
  if (dragFromIndex === toIndex || dragFromIndex < 0) return

  chrome.runtime.sendMessage({ type: 'REORDER_STEPS', fromIndex: dragFromIndex, toIndex }, (res) => {
    if (res?.steps) steps = res.steps
    _render()
  })
})

stepsList.addEventListener('dragend', () => {
  dragFromIndex = -1
  stepsList.querySelectorAll('.dragging').forEach((el) => el.classList.remove('dragging'))
})

// ---------------------------------------------------------------------------
// Preview / Export
// ---------------------------------------------------------------------------

copyCodeBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(codeBlock.textContent).then(() => {
    copyCodeBtn.textContent = 'Copied!'
    setTimeout(() => { copyCodeBtn.textContent = 'Copy' }, 1500)
  })
})

exportJsonBtn.addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(steps, null, 2)], { type: 'application/json' })
  _downloadBlob(blob, 'scenario.json')
})

exportPwBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'EXPORT_PLAYWRIGHT', steps }, (res) => {
    if (!res?.ok) return
    const blob = new Blob([res.code], { type: 'text/javascript' })
    _downloadBlob(blob, 'scenario.spec.js')
  })
})

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

const STEP_ICONS = {
  navigate: '🌐', click: '👆', fill: '✏️', press: '⌨️', type: '⌨️',
  select: '🔽', submit: '📤', wait_element: '⏳', wait_time: '⏱️',
  assert_text: '🔍', assert_visible: '👁️', assert_url: '🔗',
  screenshot: '📸', hover: '🖱️', scroll: '↕️', extract: '📋',
  drag: '🔀', upload: '📁',
}

function _render() {
  if (recording) {
    recordBtn.classList.add('recording')
    recordLabel.textContent = 'Stop'
  } else {
    recordBtn.classList.remove('recording')
    recordLabel.textContent = 'Record'
  }

  stepCount.textContent = steps.length
  clearBtn.disabled = steps.length === 0

  if (editingMonitorId) {
    sendBtn.textContent = 'Update Monitor'
    triggerBtn.classList.remove('hidden')
  } else {
    sendBtn.textContent = 'Send to WhatIsUp'
    triggerBtn.classList.add('hidden')
  }

  if (steps.length === 0) {
    emptyMsg.style.display = 'block'
    stepsList.querySelectorAll('.step-item, .step-edit').forEach((el) => el.remove())
    tabBar.style.display = 'none'
    Object.values(panels).forEach((p) => { p.style.display = 'none' })
    return
  }

  emptyMsg.style.display = 'none'
  tabBar.style.display = 'flex'
  _renderTabs()

  stepsList.querySelectorAll('.step-item, .step-edit').forEach((el) => el.remove())

  steps.forEach((step, i) => {
    stepsList.appendChild(_createStepEl(step, i))
    if (editingStepIndex === i) {
      stepsList.appendChild(_createEditEl(step, i))
    }
  })
}

function _createStepEl(step, index) {
  const el = document.createElement('div')
  el.className = 'step-item'
  el.dataset.index = index
  el.draggable = true

  const grip = document.createElement('span')
  grip.className = 'step-grip'
  grip.textContent = '⠿'

  const iconEl = document.createElement('span')
  iconEl.className = 'step-icon'
  iconEl.textContent = STEP_ICONS[step.type] ?? '▶️'

  const labelEl = document.createElement('span')
  labelEl.className = 'step-label'
  labelEl.dataset.index = index
  labelEl.textContent = step.label ?? step.type
  labelEl.title = 'Click to edit'

  const removeBtn = document.createElement('button')
  removeBtn.className = 'step-remove'
  removeBtn.dataset.index = index
  removeBtn.title = 'Remove'
  removeBtn.textContent = '✕'

  el.appendChild(grip)
  el.appendChild(iconEl)
  el.appendChild(labelEl)
  el.appendChild(removeBtn)
  return el
}

function _createEditEl(step, index) {
  const el = document.createElement('div')
  el.className = 'step-edit'

  const badge = document.createElement('span')
  badge.className = 'type-badge'
  badge.textContent = step.type
  el.appendChild(badge)

  const params = step.params || {}
  const inputs = {}

  for (const [key, val] of Object.entries(params)) {
    if (['selectors', 'timestamp', 'sourceSelectors', 'targetSelectors'].includes(key)) continue
    if (typeof val === 'object') continue

    const label = document.createElement('label')
    label.textContent = key
    const input = document.createElement('input')
    input.value = val ?? ''
    input.name = key
    inputs[key] = input

    el.appendChild(label)
    el.appendChild(input)
  }

  const actions = document.createElement('div')
  actions.className = 'edit-actions'

  const saveBtn = document.createElement('button')
  saveBtn.className = 'btn btn-primary btn-sm'
  saveBtn.textContent = 'Save'
  saveBtn.addEventListener('click', () => {
    const updatedParams = { ...params }
    for (const [key, input] of Object.entries(inputs)) {
      updatedParams[key] = input.value
    }
    const updatedStep = { ...step, params: updatedParams }
    chrome.runtime.sendMessage({ type: 'UPDATE_STEP', index, step: updatedStep }, (res) => {
      if (res?.steps) steps = res.steps
      editingStepIndex = -1
      _render()
    })
  })

  const cancelBtn = document.createElement('button')
  cancelBtn.className = 'btn btn-ghost btn-sm'
  cancelBtn.textContent = 'Cancel'
  cancelBtn.addEventListener('click', () => {
    editingStepIndex = -1
    _render()
  })

  actions.appendChild(saveBtn)
  actions.appendChild(cancelBtn)
  el.appendChild(actions)

  return el
}

function _renderTabs() {
  tabBar.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === activeTab)
  })

  for (const [key, panel] of Object.entries(panels)) {
    if (key === activeTab) {
      panel.style.display = 'block'
      panel.classList.add('visible')
    } else {
      panel.style.display = 'none'
      panel.classList.remove('visible')
    }
  }

  if (activeTab === 'preview') {
    chrome.runtime.sendMessage({ type: 'EXPORT_PLAYWRIGHT', steps }, (res) => {
      codeBlock.textContent = res?.ok ? res.code : 'Error generating code'
    })
  }
}

function _showStatus(text, ok) {
  statusMsg.textContent = (ok ? '✓ ' : '✗ ') + text
  statusMsg.className = `status-msg ${ok ? 'status-ok' : 'status-err'}`
  statusMsg.style.display = 'block'
}

function _hideStatus() {
  statusMsg.style.display = 'none'
}
