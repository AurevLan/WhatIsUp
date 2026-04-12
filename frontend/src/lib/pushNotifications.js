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

  return new Promise((resolve) => {
    let regHandle
    let errHandle
    const cleanup = () => {
      regHandle?.remove?.()
      errHandle?.remove?.()
    }

    PushNotifications.addListener('registration', async (token) => {
      cleanup()
      try {
        const { data } = await api.post('/notifications/devices', {
          token: token.value,
          platform: 'android',
          label: 'mobile',
        })
        localStorage.setItem(STORAGE_DEVICE_ID, data.id)
        localStorage.setItem(STORAGE_DEVICE_KEY, data.encryption_key)
        resolve({ ok: true, deviceId: data.id, created: data.created })
      } catch (e) {
        resolve({ ok: false, reason: 'register_failed', error: e?.message })
      }
    }).then((h) => { regHandle = h })

    PushNotifications.addListener('registrationError', (err) => {
      cleanup()
      resolve({ ok: false, reason: 'fcm_error', error: err?.error || 'unknown' })
    }).then((h) => { errHandle = h })

    PushNotifications.register().catch((e) => {
      cleanup()
      resolve({ ok: false, reason: 'register_call_failed', error: e?.message })
    })
  })
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
    const monitorId = action?.notification?.data?.monitor_id
    if (monitorId && router) {
      router.push(`/monitors/${monitorId}`)
    }
  })
}
