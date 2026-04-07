/**
 * WhatIsUp Recorder — background service worker (v2).
 *
 * Responsibilities:
 * - Maintain recording state (steps array)
 * - Receive events from content_script via chrome.runtime.onMessage
 * - Send/update scenarios to the WhatIsUp API
 * - List monitors, load/edit existing scenarios, trigger checks
 * - Generate Playwright code from steps
 */

'use strict'

// ---------------------------------------------------------------------------
// State helpers — chrome.storage.session survives SW restarts
// ---------------------------------------------------------------------------

async function _getState() {
  const data = await chrome.storage.session.get([
    'recording', 'steps', 'recordingTabId', 'secretVars', 'editingMonitorId',
  ])
  return {
    recording: data.recording ?? false,
    steps: data.steps ?? [],
    recordingTabId: data.recordingTabId ?? null,
    secretVars: data.secretVars ?? [],
    editingMonitorId: data.editingMonitorId ?? null,
  }
}

function _setState(patch) {
  return chrome.storage.session.set(patch)
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function _isValidUuid(str) {
  return typeof str === 'string' && UUID_RE.test(str)
}

// ---------------------------------------------------------------------------
// Message router — only accept messages from this extension
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // Security: reject messages not originating from our own extension
  if (sender.id !== chrome.runtime.id) {
    sendResponse({ ok: false, error: 'Unauthorized sender' })
    return true
  }

  _handleMessage(msg)
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: err.message }))
  return true
})

async function _handleMessage(msg) {
  const state = await _getState()

  switch (msg.type) {
    case 'GET_STATE':
      return {
        recording: state.recording,
        steps: state.steps,
        editingMonitorId: state.editingMonitorId,
      }

    case 'START_RECORDING': {
      const tabId = msg.tabId ?? null
      await _setState({ recording: true, steps: [], secretVars: [], recordingTabId: tabId, editingMonitorId: null })
      await _injectContentScript(tabId)
      _notifyContentScript(tabId, { type: 'RECORDING_STARTED' })
      return { ok: true }
    }

    case 'STOP_RECORDING':
      if (state.recordingTabId) {
        _notifyContentScript(state.recordingTabId, { type: 'RECORDING_STOPPED' })
      }
      await _setState({ recording: false, recordingTabId: null })
      return { ok: true, steps: state.steps }

    case 'CLEAR_STEPS':
      await _setState({ steps: [], secretVars: [], editingMonitorId: null })
      return { ok: true }

    case 'ADD_STEP': {
      if (!state.recording) return { ok: true }
      const newSteps = [...state.steps, msg.step]
      await _setState({ steps: newSteps })
      chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps: newSteps }).catch(() => {})
      return { ok: true }
    }

    case 'REMOVE_STEP': {
      const idx = msg.index
      const newSteps = [...state.steps]
      if (idx >= 0 && idx < newSteps.length) newSteps.splice(idx, 1)
      await _setState({ steps: newSteps })
      return { ok: true, steps: newSteps }
    }

    case 'REORDER_STEPS': {
      const newSteps = [...state.steps]
      const [moved] = newSteps.splice(msg.fromIndex, 1)
      if (moved) newSteps.splice(msg.toIndex, 0, moved)
      await _setState({ steps: newSteps })
      chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps: newSteps }).catch(() => {})
      return { ok: true, steps: newSteps }
    }

    case 'UPDATE_STEP': {
      const newSteps = [...state.steps]
      if (msg.index >= 0 && msg.index < newSteps.length) {
        newSteps[msg.index] = msg.step
      }
      await _setState({ steps: newSteps })
      chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps: newSteps }).catch(() => {})
      return { ok: true, steps: newSteps }
    }

    case 'ADD_SECRET_VAR': {
      if (!state.recording) return { ok: true }
      const filtered = state.secretVars.filter((v) => v.name !== msg.name)
      const newSecretVars = [...filtered, { name: msg.name, value: msg.value, secret: true }]
      await _setState({ secretVars: newSecretVars })
      return { ok: true }
    }

    case 'SEND_TO_WHATISUP': {
      if (state.editingMonitorId) {
        const result = await _updateMonitor(state.editingMonitorId, msg.steps, state.secretVars)
        return { ok: true, result, updated: true }
      }
      const result = await _sendToWhatIsUp(msg.monitorName, msg.steps, state.secretVars)
      return { ok: true, result }
    }

    case 'LIST_MONITORS': {
      const monitors = await _listMonitors()
      return { ok: true, monitors }
    }

    case 'LOAD_MONITOR': {
      if (!_isValidUuid(msg.monitorId)) throw new Error('Invalid monitor ID')
      const monitor = await _loadMonitor(msg.monitorId)
      const steps = monitor.scenario_steps || []
      await _setState({ steps, editingMonitorId: msg.monitorId })
      chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps }).catch(() => {})
      return { ok: true, monitor, steps }
    }

    case 'UPDATE_MONITOR': {
      if (!_isValidUuid(msg.monitorId)) throw new Error('Invalid monitor ID')
      await _updateMonitor(msg.monitorId, msg.steps, msg.secretVars || [])
      return { ok: true }
    }

    case 'TRIGGER_CHECK': {
      if (!_isValidUuid(msg.monitorId)) throw new Error('Invalid monitor ID')
      await _triggerCheck(msg.monitorId)
      return { ok: true }
    }

    case 'EXPORT_PLAYWRIGHT': {
      const code = _generatePlaywright(msg.steps || state.steps)
      return { ok: true, code }
    }

    default:
      return { ok: false, error: 'Unknown message type' }
  }
}

// ---------------------------------------------------------------------------
// Navigation tracking (adds "navigate" steps automatically)
// ---------------------------------------------------------------------------

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  const { recording, steps, recordingTabId } = await _getState()
  if (!recording || tabId !== recordingTabId) return
  if (changeInfo.status !== 'complete' || !tab.url) return
  if (tab.url.startsWith('chrome://') || tab.url.startsWith('about:')) return

  await _injectContentScript(tabId)
  _notifyContentScript(tabId, { type: 'RECORDING_STARTED' })

  const last = steps[steps.length - 1]
  if (last && last.type === 'navigate' && last.params.url === tab.url) return

  const newSteps = [
    ...steps,
    {
      type: 'navigate',
      label: `Navigate to ${tab.url}`,
      params: { url: tab.url, timestamp: Date.now() },
    },
  ]
  await _setState({ steps: newSteps })
  chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps: newSteps }).catch(() => {})
})

// ---------------------------------------------------------------------------
// WhatIsUp API calls
// ---------------------------------------------------------------------------

async function _getApiConfig() {
  const { serverUrl, apiKey } = await chrome.storage.local.get(['serverUrl', 'apiKey'])
  if (!serverUrl || !apiKey) {
    throw new Error('WhatIsUp server URL and API key are required. Go to Extension Options.')
  }
  const cleaned = serverUrl.replace(/\/$/, '')
  // Security: reject non-HTTPS URLs (allow localhost for dev)
  const url = new URL(cleaned)
  const isLocalhost = url.hostname === 'localhost' || url.hostname === '127.0.0.1' || url.hostname === '::1'
  if (url.protocol !== 'https:' && !isLocalhost) {
    throw new Error('Server URL must use HTTPS (HTTP allowed only for localhost).')
  }
  return { serverUrl: cleaned, apiKey }
}

async function _sendToWhatIsUp(monitorName, scenarioSteps, secretVars = []) {
  const { serverUrl, apiKey } = await _getApiConfig()

  const body = {
    name: monitorName,
    url: scenarioSteps.find((s) => s.type === 'navigate')?.params?.url ?? 'https://example.com',
    check_type: 'scenario',
    scenario_steps: scenarioSteps,
    scenario_variables: secretVars,
    interval_seconds: 300,
    timeout_seconds: 30,
  }

  const response = await fetch(`${serverUrl}/api/v1/monitors/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`API error ${response.status}: ${text}`)
  }
  return response.json()
}

async function _listMonitors() {
  const { serverUrl, apiKey } = await _getApiConfig()
  const response = await fetch(`${serverUrl}/api/v1/monitors/?check_type=scenario`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!response.ok) throw new Error(`API error ${response.status}`)
  const data = await response.json()
  return Array.isArray(data) ? data : data.items || []
}

async function _loadMonitor(monitorId) {
  const { serverUrl, apiKey } = await _getApiConfig()
  const response = await fetch(`${serverUrl}/api/v1/monitors/${monitorId}`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!response.ok) throw new Error(`API error ${response.status}`)
  return response.json()
}

async function _updateMonitor(monitorId, steps, secretVars = []) {
  const { serverUrl, apiKey } = await _getApiConfig()
  const response = await fetch(`${serverUrl}/api/v1/monitors/${monitorId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ scenario_steps: steps, scenario_variables: secretVars }),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`API error ${response.status}: ${text}`)
  }
  return response.json()
}

async function _triggerCheck(monitorId) {
  const { serverUrl, apiKey } = await _getApiConfig()
  const response = await fetch(`${serverUrl}/api/v1/monitors/${monitorId}/trigger-check`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!response.ok) throw new Error(`API error ${response.status}`)
  return response.json()
}

// ---------------------------------------------------------------------------
// Playwright code generation
// ---------------------------------------------------------------------------

function _generatePlaywright(steps) {
  const lines = [
    "const { test, expect } = require('@playwright/test');",
    '',
    "test('WhatIsUp recorded scenario', async ({ page }) => {",
  ]

  for (const step of steps) {
    const p = step.params || {}
    const sel = p.selector ? `'${_escJs(p.selector)}'` : "'body'"

    switch (step.type) {
      case 'navigate':
        lines.push(`  await page.goto('${_escJs(p.url)}');`)
        break
      case 'click':
        lines.push(`  await page.click(${sel});`)
        break
      case 'fill':
        lines.push(`  await page.fill(${sel}, '${_escJs(p.value || '')}');`)
        break
      case 'type':
        lines.push(`  await page.type(${sel}, '${_escJs(p.text || '')}');`)
        break
      case 'press':
        lines.push(`  await page.press(${sel}, '${_escJs(p.key || 'Tab')}');`)
        break
      case 'select':
        lines.push(`  await page.selectOption(${sel}, '${_escJs(p.value || '')}');`)
        break
      case 'hover':
        lines.push(`  await page.hover(${sel});`)
        break
      case 'scroll':
        lines.push(`  await page.evaluate(() => window.scrollTo(${p.x || 0}, ${p.y || 0}));`)
        break
      case 'wait_element':
        lines.push(`  await page.waitForSelector(${sel});`)
        break
      case 'wait_time':
        lines.push(`  await page.waitForTimeout(${p.ms || 1000});`)
        break
      case 'assert_text':
        lines.push(`  await expect(page.locator(${sel})).toContainText('${_escJs(p.text || '')}');`)
        break
      case 'assert_visible':
        lines.push(`  await expect(page.locator(${sel})).toBeVisible();`)
        break
      case 'assert_url':
        lines.push(`  await expect(page).toHaveURL('${_escJs(p.url || '')}');`)
        break
      case 'screenshot':
        lines.push('  await page.screenshot();')
        break
      case 'drag':
        lines.push(`  await page.dragAndDrop('${_escJs(p.sourceSelector || '')}', '${_escJs(p.targetSelector || '')}');`)
        break
      case 'upload':
        lines.push(`  await page.setInputFiles(${sel}, [${(p.fileNames || []).map((f) => `'${_escJs(f)}'`).join(', ')}]);`)
        break
      default:
        lines.push(`  // Unknown step type: ${step.type}`)
    }
  }

  lines.push('});')
  lines.push('')
  return lines.join('\n')
}

function _escJs(str) {
  return (str || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'")
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _notifyContentScript(tabId, message) {
  if (!tabId) return
  chrome.tabs.sendMessage(tabId, message).catch(() => {})
}

/**
 * Programmatically inject the content script into the target tab.
 * This avoids injecting into every page globally (reduced attack surface).
 * Re-injection is safe — the script guards against duplicate listeners.
 */
async function _injectContentScript(tabId) {
  if (!tabId) return
  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      files: ['content_script.js'],
    })
  } catch {
    // Tab may not be injectable (chrome://, devtools, etc.) — ignore
  }
}
