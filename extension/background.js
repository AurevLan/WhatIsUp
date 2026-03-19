/**
 * WhatIsUp Recorder — background service worker.
 *
 * Responsibilities:
 * - Maintain recording state (steps array)
 * - Receive events from content_script via chrome.runtime.onMessage
 * - Send the recorded scenario to the WhatIsUp API
 *
 * State is stored in chrome.storage.session so it survives service worker
 * restarts (MV3 workers are terminated after a few seconds of inactivity).
 */

'use strict'

// ---------------------------------------------------------------------------
// State helpers — chrome.storage.session survives SW restarts
// ---------------------------------------------------------------------------

async function _getState() {
  const data = await chrome.storage.session.get(['recording', 'steps', 'recordingTabId', 'secretVars'])
  return {
    recording: data.recording ?? false,
    steps: data.steps ?? [],
    recordingTabId: data.recordingTabId ?? null,
    secretVars: data.secretVars ?? [],
  }
}

function _setState(patch) {
  return chrome.storage.session.set(patch)
}

// ---------------------------------------------------------------------------
// Message router
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  _handleMessage(msg)
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: err.message }))
  return true // keep channel open for async response
})

async function _handleMessage(msg) {
  const state = await _getState()

  switch (msg.type) {
    case 'GET_STATE':
      return { recording: state.recording, steps: state.steps }

    case 'START_RECORDING': {
      const tabId = msg.tabId ?? null
      await _setState({ recording: true, steps: [], secretVars: [], recordingTabId: tabId })
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
      await _setState({ steps: [], secretVars: [] })
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

    case 'ADD_SECRET_VAR': {
      if (!state.recording) return { ok: true }
      // Replace existing var with same name if present (user retyped)
      const filtered = state.secretVars.filter((v) => v.name !== msg.name)
      const newSecretVars = [...filtered, { name: msg.name, value: msg.value, secret: true }]
      await _setState({ secretVars: newSecretVars })
      return { ok: true }
    }

    case 'SEND_TO_WHATISUP': {
      const result = await _sendToWhatIsUp(msg.monitorName, msg.steps, state.secretVars)
      return { ok: true, result }
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

  // Re-activate content script on the newly loaded page
  _notifyContentScript(tabId, { type: 'RECORDING_STARTED' })

  // Avoid duplicate navigate steps for the same URL
  const last = steps[steps.length - 1]
  if (last && last.type === 'navigate' && last.params.url === tab.url) return

  const newSteps = [
    ...steps,
    {
      type: 'navigate',
      label: `Navigate to ${tab.url}`,
      params: { url: tab.url },
    },
  ]
  await _setState({ steps: newSteps })
  chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps: newSteps }).catch(() => {})
})

// ---------------------------------------------------------------------------
// WhatIsUp API call
// ---------------------------------------------------------------------------

async function _sendToWhatIsUp(monitorName, scenarioSteps, secretVars = []) {
  const { serverUrl, apiKey } = await chrome.storage.local.get(['serverUrl', 'apiKey'])

  if (!serverUrl || !apiKey) {
    throw new Error('WhatIsUp server URL and API key are required. Go to Extension Options.')
  }

  const url = `${serverUrl.replace(/\/$/, '')}/api/v1/monitors/`

  const body = {
    name: monitorName,
    url: scenarioSteps.find((s) => s.type === 'navigate')?.params?.url ?? 'https://example.com',
    check_type: 'scenario',
    scenario_steps: scenarioSteps,
    scenario_variables: secretVars,
    interval_seconds: 300,
    timeout_seconds: 30,
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(`API error ${response.status}: ${text}`)
  }

  return response.json()
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _notifyContentScript(tabId, message) {
  if (!tabId) return
  chrome.tabs.sendMessage(tabId, message).catch(() => {
    // Tab may not have content_script injected yet — ignore
  })
}
