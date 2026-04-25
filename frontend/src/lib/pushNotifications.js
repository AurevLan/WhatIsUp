// Native push notifications via @capacitor/push-notifications.
//
// On the web build this whole module is a no-op — isPushAvailable() returns
// false and every other function resolves with `{ ok: false, reason: 'web' }`.
//
// On native (Capacitor) it requests OS permission, registers with FCM,
// POSTs the resulting token to /api/v1/notifications/devices and stores the
// returned device id + encryption key in localStorage so we can revoke later
// or decrypt payloads in a future release. Listeners route notification taps
// to the corresponding monitor detail page.

import { Capacitor } from '@capacitor/core'
import api from '../api/client'
import { isNative } from './serverConfig'

const STORAGE_DEVICE_ID = 'whatisup_device_id'
const STORAGE_DEVICE_KEY = 'whatisup_device_key'

let _foregroundListenersWired = false

export function isPushAvailable() {
  return isNative()
}

export function getRegisteredDeviceId() {
  return localStorage.getItem(STORAGE_DEVICE_ID)
}

async function _loadPlugin() {
  try {
    const mod = await import('@capacitor/push-notifications')
    return mod.PushNotifications
  } catch {
    return null
  }
}

export async function registerPushNotifications({ silentIfDenied = false } = {}) {
  if (!isNative()) return { ok: false, reason: 'web' }
  const PushNotifications = await _loadPlugin()
  if (!PushNotifications) return { ok: false, reason: 'plugin_missing' }

  let perm = await PushNotifications.checkPermissions()
  if (perm.receive !== 'granted') {
    if (silentIfDenied && perm.receive === 'denied') {
      return { ok: false, reason: 'permission_denied' }
    }
    perm = await PushNotifications.requestPermissions()
    if (perm.receive !== 'granted') {
      return { ok: false, reason: 'permission_denied' }
    }
  }

  // Wire listeners *before* calling register() so the events that follow
  // are not dropped on the floor (Capacitor 7 returns Promises from
  // addListener and the underlying handler is only attached when they
  // resolve).
  let resolveOnce
  const settled = new Promise((resolve) => { resolveOnce = resolve })
  let done = false
  const finish = (value) => {
    if (done) return
    done = true
    resolveOnce(value)
  }

  const regHandle = await PushNotifications.addListener('registration', async (token) => {
    try {
      const { data } = await api.post('/notifications/devices', {
        token: token.value,
        platform: Capacitor.getPlatform(),
        label: 'mobile',
      })
      localStorage.setItem(STORAGE_DEVICE_ID, data.id)
      localStorage.setItem(STORAGE_DEVICE_KEY, data.encryption_key)
      finish({ ok: true, deviceId: data.id, created: data.created })
    } catch (e) {
      finish({
        ok: false,
        reason: 'register_failed',
        error: e?.response?.status ? `HTTP ${e.response.status}` : (e?.message || 'unknown'),
      })
    }
  })

  const errHandle = await PushNotifications.addListener('registrationError', (err) => {
    finish({ ok: false, reason: 'fcm_error', error: err?.error || 'unknown' })
  })

  try {
    await PushNotifications.register()
  } catch (e) {
    finish({ ok: false, reason: 'register_call_failed', error: e?.message })
  }

  // Hard timeout — if FCM never answers (no Google Play Services, no internet,
  // missing google-services.json) the user would otherwise stare at a spinner.
  // 12 s is long enough for a cold start on slow networks but short enough to
  // keep the UI snappy when Firebase is simply not configured in the APK.
  const timeout = new Promise((resolve) =>
    setTimeout(
      () => resolve({ ok: false, reason: 'fcm_unavailable', error: 'no FCM response after 12s — Firebase likely not configured in this APK' }),
      12000,
    ),
  )

  const result = await Promise.race([settled, timeout])
  try { await regHandle?.remove?.() } catch { /* noop */ }
  try { await errHandle?.remove?.() } catch { /* noop */ }
  return result
}

export async function unregisterPushNotifications() {
  const deviceId = getRegisteredDeviceId()
  if (deviceId) {
    try {
      await api.delete(`/notifications/devices/${deviceId}`)
    } catch {
      // Best effort — clear local state regardless so the user can retry.
    }
  }
  localStorage.removeItem(STORAGE_DEVICE_ID)
  localStorage.removeItem(STORAGE_DEVICE_KEY)
  if (isNative()) {
    const PushNotifications = await _loadPlugin()
    if (PushNotifications?.removeAllListeners) {
      try { await PushNotifications.removeAllListeners() } catch { /* noop */ }
    }
  }
}

export async function setupForegroundListeners(router) {
  if (!isNative() || _foregroundListenersWired) return
  const PushNotifications = await _loadPlugin()
  if (!PushNotifications) return
  _foregroundListenersWired = true

  PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
    handleNotificationAction(action, router).catch(() => { /* swallow */ })
  })
}

/**
 * Dispatch a tapped notification action (T1-04).
 *
 * The Capacitor plugin reports `actionId === 'tap'` for the default body tap.
 * Action button taps surface their declared id (`ack`, `snooze_1h`, …). The
 * incident id and quick-action duration are encoded in the notification data
 * payload by the FCM channel on the backend.
 *
 * Exported so unit tests can drive it without the native plugin.
 */
export async function handleNotificationAction(action, router) {
  const data = action?.notification?.data || {}
  const monitorId = data.monitor_id
  const incidentId = data.incident_id
  const actionId = action?.actionId || 'tap'

  if (actionId === 'ack' && incidentId) {
    try { await api.post(`/incidents/${incidentId}/ack`) } catch { /* ignore */ }
  } else if (actionId.startsWith('snooze_') && incidentId) {
    // Action ids ship the duration as a suffix (snooze_1h → 60, snooze_4h → 240).
    // Backend re-validates the value, so a malformed id just no-ops.
    const minutes = actionId === 'snooze_1h' ? 60 : actionId === 'snooze_4h' ? 240 : null
    if (minutes != null) {
      try {
        await api.post(`/incidents/${incidentId}/snooze`, { duration_minutes: minutes })
      } catch { /* ignore */ }
    }
  }

  // Always surface the relevant monitor so the user lands on actionable context.
  if (monitorId && router) {
    router.push(`/monitors/${monitorId}`)
  }
}
