import { defineStore } from 'pinia'
import { ref } from 'vue'
import { webPushApi } from '../api/webPush'

/** Convert a base64url VAPID public key to a Uint8Array for PushManager.subscribe(). */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export const useWebPushStore = defineStore('webPush', () => {
  const isSupported = ref(
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
  const isSubscribed = ref(false)
  const loading = ref(false)
  const error = ref(null)
  const serverEnabled = ref(false)

  async function init() {
    if (!isSupported.value) return
    try {
      const { data } = await webPushApi.getPublicKey()
      serverEnabled.value = data.enabled
      if (!data.enabled) return

      const reg = await navigator.serviceWorker.ready
      const existing = await reg.pushManager.getSubscription()
      isSubscribed.value = !!existing
    } catch {
      // non-blocking
    }
  }

  async function subscribe() {
    if (!isSupported.value || !serverEnabled.value) return
    error.value = null
    loading.value = true
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        error.value = 'permission_denied'
        return
      }

      const { data: keyData } = await webPushApi.getPublicKey()
      const reg = await navigator.serviceWorker.ready
      const pushSub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(keyData.public_key),
      })

      const subJson = pushSub.toJSON()
      await webPushApi.subscribe({
        endpoint: subJson.endpoint,
        p256dh: subJson.keys.p256dh,
        auth: subJson.keys.auth,
        user_agent: navigator.userAgent.slice(0, 255),
      })
      isSubscribed.value = true
    } catch (err) {
      error.value = err.message || 'unknown_error'
    } finally {
      loading.value = false
    }
  }

  async function unsubscribe() {
    error.value = null
    loading.value = true
    try {
      const reg = await navigator.serviceWorker.ready
      const pushSub = await reg.pushManager.getSubscription()
      if (pushSub) await pushSub.unsubscribe()
      await webPushApi.unsubscribe()
      isSubscribed.value = false
    } catch (err) {
      error.value = err.message || 'unknown_error'
    } finally {
      loading.value = false
    }
  }

  async function sendTest() {
    await webPushApi.test()
  }

  return { isSupported, isSubscribed, loading, error, serverEnabled, init, subscribe, unsubscribe, sendTest }
})
