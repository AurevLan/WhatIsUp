import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const apiGetPublicKey = vi.fn()
const apiSubscribe = vi.fn()
const apiUnsubscribe = vi.fn()
const apiTest = vi.fn()

vi.mock('../../src/api/webPush', () => ({
  webPushApi: {
    getPublicKey: (...a) => apiGetPublicKey(...a),
    subscribe: (...a) => apiSubscribe(...a),
    unsubscribe: (...a) => apiUnsubscribe(...a),
    test: (...a) => apiTest(...a),
  },
}))

import { useWebPushStore } from '../../src/stores/webPush'

// Push subscription returned by pushManager.subscribe()
function makePushSub({ endpoint = 'https://fcm.example/sub', p256dh = 'p256', auth = 'authk' } = {}) {
  const sub = {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh, auth } }),
    unsubscribe: vi.fn(async () => true),
  }
  return sub
}

let pushSubInstance = null
let originalNavigator
let originalWindow

beforeEach(() => {
  setActivePinia(createPinia())
  apiGetPublicKey.mockReset()
  apiSubscribe.mockReset()
  apiUnsubscribe.mockReset()
  apiTest.mockReset()
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})

  originalNavigator = globalThis.navigator
  originalWindow = globalThis.window

  pushSubInstance = makePushSub()

  // Default: no existing subscription. Individual tests that need an existing
  // sub at init() time override `getSubscription` after `useWebPushStore()`.
  const reg = {
    pushManager: {
      subscribe: vi.fn(async () => pushSubInstance),
      getSubscription: vi.fn(async () => null),
    },
  }
  globalThis.__pushReg = reg

  globalThis.navigator = {
    serviceWorker: { ready: Promise.resolve(reg) },
    userAgent: 'Mozilla/5.0 (jsdom)',
  }
  globalThis.window = {
    PushManager: function () {},
    Notification: { requestPermission: vi.fn(async () => 'granted') },
  }
  globalThis.Notification = globalThis.window.Notification
})

afterEach(() => {
  globalThis.navigator = originalNavigator
  globalThis.window = originalWindow
})

import { afterEach } from 'vitest'

describe('webPush store', () => {
  it('init does nothing when push is not supported in this env', async () => {
    // The store reads `isSupported` at construction time from the live navigator/
    // window globals that vitest sets up. We can't easily un-support it after
    // import, so we just assert the store gracefully handles unsupported state
    // by stubbing isSupported.value=false post-construction.
    const store = useWebPushStore()
    store.isSupported = false
    await store.init()
    expect(apiGetPublicKey).not.toHaveBeenCalled()
  })

  it('init pulls server config and stays subscribed when SW reports an existing sub', async () => {
    apiGetPublicKey.mockResolvedValueOnce({ data: { enabled: true, public_key: 'k' } })
    globalThis.__pushReg.pushManager.getSubscription = vi.fn(async () => pushSubInstance)
    const store = useWebPushStore()
    await store.init()
    expect(store.serverEnabled).toBe(true)
    expect(store.isSubscribed).toBe(true)
  })

  it('init short-circuits when server has push disabled', async () => {
    apiGetPublicKey.mockResolvedValueOnce({ data: { enabled: false } })
    const store = useWebPushStore()
    await store.init()
    expect(store.serverEnabled).toBe(false)
    expect(store.isSubscribed).toBe(false)
  })

  it('init swallows API errors silently (non-blocking)', async () => {
    apiGetPublicKey.mockRejectedValueOnce(new Error('boom'))
    const store = useWebPushStore()
    await store.init()
    expect(store.error).toBe(null)
  })

  it('subscribe records permission_denied and returns early when user refuses', async () => {
    globalThis.Notification.requestPermission = vi.fn(async () => 'denied')
    apiGetPublicKey.mockResolvedValueOnce({ data: { enabled: true, public_key: 'k' } })

    const store = useWebPushStore()
    await store.init()
    await store.subscribe()

    expect(store.error).toBe('permission_denied')
    expect(store.isSubscribed).toBe(false)
    expect(apiSubscribe).not.toHaveBeenCalled()
  })

  it('subscribe runs the full happy path and posts the sub to the server', async () => {
    apiGetPublicKey.mockResolvedValue({ data: { enabled: true, public_key: 'AAECAwQFBg' } })
    apiSubscribe.mockResolvedValueOnce({ data: { ok: true } })

    const store = useWebPushStore()
    await store.init()
    await store.subscribe()

    expect(apiSubscribe).toHaveBeenCalledWith(expect.objectContaining({
      endpoint: 'https://fcm.example/sub',
      p256dh: 'p256',
      auth: 'authk',
    }))
    expect(store.isSubscribed).toBe(true)
    expect(store.error).toBe(null)
    expect(store.loading).toBe(false)
  })

  it('subscribe surfaces the API error message when server rejects', async () => {
    apiGetPublicKey.mockResolvedValue({ data: { enabled: true, public_key: 'AAECAwQFBg' } })
    apiSubscribe.mockRejectedValueOnce(new Error('server is angry'))

    const store = useWebPushStore()
    await store.init()
    await store.subscribe()

    expect(store.error).toBe('server is angry')
    expect(store.isSubscribed).toBe(false)
    expect(store.loading).toBe(false)
  })

  it('subscribe is a no-op when server-side push is disabled', async () => {
    apiGetPublicKey.mockResolvedValueOnce({ data: { enabled: false } })
    const store = useWebPushStore()
    await store.init()
    await store.subscribe()
    expect(apiSubscribe).not.toHaveBeenCalled()
  })

  it('unsubscribe calls the browser SW + the server endpoint', async () => {
    apiGetPublicKey.mockResolvedValue({ data: { enabled: true, public_key: 'AAEC' } })
    apiUnsubscribe.mockResolvedValueOnce({ data: { ok: true } })
    globalThis.__pushReg.pushManager.getSubscription = vi.fn(async () => pushSubInstance)

    const store = useWebPushStore()
    await store.init()
    await store.unsubscribe()

    expect(pushSubInstance.unsubscribe).toHaveBeenCalled()
    expect(apiUnsubscribe).toHaveBeenCalled()
    expect(store.isSubscribed).toBe(false)
  })

  it('sendTest delegates straight to the API', async () => {
    apiTest.mockResolvedValueOnce({ data: { ok: true } })
    const store = useWebPushStore()
    await store.sendTest()
    expect(apiTest).toHaveBeenCalledTimes(1)
  })
})
