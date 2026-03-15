'use strict'

const serverUrlInput = document.getElementById('serverUrl')
const apiKeyInput = document.getElementById('apiKey')
const saveBtn = document.getElementById('saveBtn')
const testBtn = document.getElementById('testBtn')
const statusMsg = document.getElementById('statusMsg')

// ---------------------------------------------------------------------------
// Load saved values
// ---------------------------------------------------------------------------

chrome.storage.sync.get(['serverUrl', 'apiKey'], ({ serverUrl, apiKey }) => {
  if (serverUrl) serverUrlInput.value = serverUrl
  if (apiKey) apiKeyInput.value = apiKey
})

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

saveBtn.addEventListener('click', () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/$/, '')
  const apiKey = apiKeyInput.value.trim()

  if (!serverUrl) {
    _status('Server URL is required.', false)
    return
  }

  if (!apiKey.startsWith('wiu_u_')) {
    _status('API key must start with wiu_u_', false)
    return
  }

  chrome.storage.sync.set({ serverUrl, apiKey }, () => {
    _status('Saved!', true)
  })
})

// ---------------------------------------------------------------------------
// Test connection
// ---------------------------------------------------------------------------

testBtn.addEventListener('click', async () => {
  const serverUrl = serverUrlInput.value.trim().replace(/\/$/, '')
  const apiKey = apiKeyInput.value.trim()

  if (!serverUrl || !apiKey) {
    _status('Fill in both fields first.', false)
    return
  }

  testBtn.disabled = true
  testBtn.textContent = 'Testing…'
  _hideStatus()

  try {
    const res = await fetch(`${serverUrl}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    })

    if (res.ok) {
      const data = await res.json()
      _status(`✓ Connected as ${data.username}`, true)
    } else if (res.status === 401) {
      _status('✗ Invalid API key or server URL.', false)
    } else {
      _status(`✗ Server returned ${res.status}.`, false)
    }
  } catch {
    _status('✗ Could not reach the server. Check the URL.', false)
  } finally {
    testBtn.disabled = false
    testBtn.textContent = 'Test connection'
  }
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _status(text, ok) {
  statusMsg.textContent = text
  statusMsg.className = `status ${ok ? 'ok' : 'err'}`
}

function _hideStatus() {
  statusMsg.textContent = ''
  statusMsg.className = 'status'
}
