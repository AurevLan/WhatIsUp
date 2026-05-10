// "Test now" trigger + polling for MonitorDetailView.
//
// handleTriggerCheck() POSTs to /monitors/{id}/check, then polls
// /monitors/{id}/results every 3s up to 30s waiting for a result newer than
// the click timestamp. The fresh result's id is exposed via newResultId so
// the UI can flash it for 5s. All timers are cleaned up in onScopeDispose.
//
// loadResults() is also exposed so callers can refresh the results list
// when the chartWindow ref changes (the parent watches it).

import { onScopeDispose, ref } from 'vue'
import { monitorsApi, triggerCheck } from '../api/monitors'

export function useMonitorTesting(monitorRef, monitorIdRef, resultsRef, chartWindowRef) {
  const testing = ref(false)
  const testingState = ref(null) // null | 'queued' | 'running' | 'done'
  const newResultId = ref(null)
  const testingElapsed = ref(0)

  let testPollInterval = null
  let testPollTimeout = null
  let highlightTimeout = null
  let elapsedInterval = null

  async function loadResults() {
    const id = monitorIdRef.value
    const since = new Date(Date.now() - chartWindowRef.value * 60 * 60 * 1000).toISOString()
    const { data } = await monitorsApi.results(id, { limit: 2000, since })
    // Only update ref when data actually changed to avoid spurious re-renders
    const latest = data[0]
    const current = resultsRef.value[0]
    if (
      !current ||
      !latest ||
      latest.id !== current.id ||
      data.length !== resultsRef.value.length
    ) {
      resultsRef.value = data
    }
  }

  async function handleTriggerCheck() {
    if (testing.value || !monitorRef.value) return
    testing.value = true
    testingState.value = 'queued'
    newResultId.value = null
    testingElapsed.value = 0
    elapsedInterval = setInterval(() => {
      testingElapsed.value++
    }, 1000)

    const clickedAt = new Date().toISOString()

    try {
      await triggerCheck(monitorRef.value.id)
      testingState.value = 'running'
    } catch {
      clearInterval(elapsedInterval)
      elapsedInterval = null
      testingElapsed.value = 0
      testing.value = false
      testingState.value = null
      return
    }

    // Poll every 3 s; hard-cancel after 30 s
    const stopPolling = () => {
      clearInterval(testPollInterval)
      clearTimeout(testPollTimeout)
      clearInterval(elapsedInterval)
      testPollInterval = null
      testPollTimeout = null
      elapsedInterval = null
    }

    testPollTimeout = setTimeout(() => {
      stopPolling()
      testing.value = false
      testingState.value = null
    }, 30000)

    testPollInterval = setInterval(async () => {
      try {
        await loadResults()
        const fresh = resultsRef.value.find((r) => r.checked_at > clickedAt)
        if (fresh) {
          stopPolling()
          newResultId.value = fresh.id
          testingState.value = 'done'
          testing.value = false
          // Remove highlight after 5 s; track timeout for unmount cleanup
          highlightTimeout = setTimeout(() => {
            newResultId.value = null
          }, 5000)
        }
      } catch {
        // Network error — keep polling
      }
    }, 3000)
  }

  onScopeDispose(() => {
    clearInterval(testPollInterval)
    clearTimeout(testPollTimeout)
    clearTimeout(highlightTimeout)
    clearInterval(elapsedInterval)
    testPollInterval = null
    testPollTimeout = null
    highlightTimeout = null
    elapsedInterval = null
  })

  return {
    testing,
    testingState,
    newResultId,
    testingElapsed,
    loadResults,
    handleTriggerCheck,
  }
}
