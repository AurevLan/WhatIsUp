/**
 * WhatIsUp Recorder — background service worker.
 *
 * Responsibilities:
 * - Maintain recording state (steps array)
 * - Receive events from content_script via chrome.runtime.onMessage
 * - Send the recorded scenario to the WhatIsUp API
 */

'use strict'

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let recording = false
let steps = []
let recordingTabId = null

// ---------------------------------------------------------------------------
// Message router
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case 'GET_STATE':
      sendResponse({ recording, steps })
      break

    case 'START_RECORDING': {
      recording = true
      steps = []
      recordingTabId = msg.tabId ?? null
      // Notify the active tab so content_script activates event listeners
      _notifyContentScript(recordingTabId, { type: 'RECORDING_STARTED' })
      sendResponse({ ok: true })
      break
    }

    case 'STOP_RECORDING':
      recording = false
      if (recordingTabId) {
        _notifyContentScript(recordingTabId, { type: 'RECORDING_STOPPED' })
      }
      recordingTabId = null
      sendResponse({ ok: true, steps })
      break

    case 'CLEAR_STEPS':
      steps = []
      sendResponse({ ok: true })
      break

    case 'ADD_STEP':
      if (recording) {
        steps.push(msg.step)
        // Broadcast to popup so it updates in real-time
        chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps }).catch(() => {})
      }
      sendResponse({ ok: true })
      break

    case 'REMOVE_STEP': {
      const idx = msg.index
      if (idx >= 0 && idx < steps.length) steps.splice(idx, 1)
      sendResponse({ ok: true, steps })
      break
    }

    case 'SEND_TO_WHATISUP':
      _sendToWhatIsUp(msg.monitorName, msg.steps)
        .then((result) => sendResponse({ ok: true, result }))
        .catch((err) => sendResponse({ ok: false, error: err.message }))
      return true // keep channel open for async response

    default:
      sendResponse({ ok: false, error: 'Unknown message type' })
  }
  return false
})

// ---------------------------------------------------------------------------
// Navigation tracking (adds "navigate" steps automatically)
// ---------------------------------------------------------------------------

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!recording || tabId !== recordingTabId) return
  if (changeInfo.status !== 'complete' || !tab.url) return
  if (tab.url.startsWith('chrome://') || tab.url.startsWith('about:')) return

  // Avoid duplicate navigate steps for the same URL
  const last = steps[steps.length - 1]
  if (last && last.type === 'navigate' && last.params.url === tab.url) return

  steps.push({
    type: 'navigate',
    label: `Navigate to ${tab.url}`,
    params: { url: tab.url },
  })
  chrome.runtime.sendMessage({ type: 'STEPS_UPDATED', steps }).catch(() => {})
})

// ---------------------------------------------------------------------------
// WhatIsUp API call
// ---------------------------------------------------------------------------

async function _sendToWhatIsUp(monitorName, scenarioSteps) {
  const { serverUrl, apiKey } = await chrome.storage.sync.get(['serverUrl', 'apiKey'])

  if (!serverUrl || !apiKey) {
    throw new Error('WhatIsUp server URL and API key are required. Go to Extension Options.')
  }

  const url = `${serverUrl.replace(/\/$/, '')}/api/v1/monitors`

  const body = {
    name: monitorName,
    url: scenarioSteps.find((s) => s.type === 'navigate')?.params?.url ?? 'https://example.com',
    check_type: 'scenario',
    scenario_steps: scenarioSteps,
    scenario_variables: [],
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
