/**
 * Tests for frontend/src/lib/nativeApp.js
 *
 * Covers: setupBackButton() back/exit routing, setupAppStateListeners()
 * WebSocket suspend on background / resume on foreground, and the isNative()
 * guard that makes every function a no-op on the web build.
 *
 * @capacitor/app and serverConfig are fully mocked — these tests run in Node
 * (jsdom) with no native platform present.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ── Hoisted mocks (available before vi.mock is evaluated) ─────────────────────

const { isNativeMock } = vi.hoisted(() => ({
  isNativeMock: vi.fn(() => true),
}))

const mockExitApp = vi.fn()
const mockAddListener = vi.fn()

vi.mock('@capacitor/app', () => ({
  App: {
    addListener: mockAddListener,
    exitApp: mockExitApp,
  },
}))

vi.mock('../src/lib/serverConfig', () => ({
  isNative: isNativeMock,
}))

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Return the handler registered for the given event name by scanning
 * all `App.addListener` calls made so far.
 */
function capturedHandler(eventName) {
  const call = mockAddListener.mock.calls.find(([ev]) => ev === eventName)
  return call ? call[1] : null
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  // Default: simulate native build
  isNativeMock.mockReturnValue(true)
})

// ── setupBackButton ───────────────────────────────────────────────────────────

describe('setupBackButton', () => {
  it('registers a backButton listener when native', async () => {
    const { setupBackButton } = await import('../src/lib/nativeApp.js')
    const router = { back: vi.fn() }
    await setupBackButton(router)
    expect(mockAddListener).toHaveBeenCalledWith('backButton', expect.any(Function))
  })

  it('calls router.back() when canGoBack is true', async () => {
    const { setupBackButton } = await import('../src/lib/nativeApp.js')
    const router = { back: vi.fn() }
    await setupBackButton(router)

    const handler = capturedHandler('backButton')
    expect(handler).not.toBeNull()
    handler({ canGoBack: true })

    expect(router.back).toHaveBeenCalledOnce()
    expect(mockExitApp).not.toHaveBeenCalled()
  })

  it('calls App.exitApp() when at root (canGoBack false)', async () => {
    const { setupBackButton } = await import('../src/lib/nativeApp.js')
    const router = { back: vi.fn() }
    await setupBackButton(router)

    const handler = capturedHandler('backButton')
    handler({ canGoBack: false })

    expect(mockExitApp).toHaveBeenCalledOnce()
    expect(router.back).not.toHaveBeenCalled()
  })

  it('is a no-op on web build (isNative returns false)', async () => {
    isNativeMock.mockReturnValue(false)
    const { setupBackButton } = await import('../src/lib/nativeApp.js')
    const router = { back: vi.fn() }
    await setupBackButton(router)
    expect(mockAddListener).not.toHaveBeenCalled()
  })
})

// ── setupAppStateListeners ────────────────────────────────────────────────────

describe('setupAppStateListeners — WebSocket suspend/resume', () => {
  it('registers an appStateChange listener when native', async () => {
    const { setupAppStateListeners } = await import('../src/lib/nativeApp.js')
    const wsStore = { connect: vi.fn(), disconnect: vi.fn() }
    await setupAppStateListeners(wsStore)
    expect(mockAddListener).toHaveBeenCalledWith('appStateChange', expect.any(Function))
  })

  it('calls wsStore.disconnect() when app goes to background (isActive: false)', async () => {
    const { setupAppStateListeners } = await import('../src/lib/nativeApp.js')
    const wsStore = { connect: vi.fn(), disconnect: vi.fn() }
    await setupAppStateListeners(wsStore)

    const handler = capturedHandler('appStateChange')
    expect(handler).not.toBeNull()
    handler({ isActive: false })

    expect(wsStore.disconnect).toHaveBeenCalledOnce()
    expect(wsStore.connect).not.toHaveBeenCalled()
  })

  it('calls wsStore.connect() when app returns to foreground (isActive: true)', async () => {
    const { setupAppStateListeners } = await import('../src/lib/nativeApp.js')
    const wsStore = { connect: vi.fn(), disconnect: vi.fn() }
    await setupAppStateListeners(wsStore)

    const handler = capturedHandler('appStateChange')
    handler({ isActive: true })

    expect(wsStore.connect).toHaveBeenCalledOnce()
    expect(wsStore.disconnect).not.toHaveBeenCalled()
  })

  it('models a background→foreground cycle: disconnect then connect', async () => {
    const { setupAppStateListeners } = await import('../src/lib/nativeApp.js')
    const wsStore = { connect: vi.fn(), disconnect: vi.fn() }
    await setupAppStateListeners(wsStore)

    const handler = capturedHandler('appStateChange')
    handler({ isActive: false })
    handler({ isActive: true })

    expect(wsStore.disconnect).toHaveBeenCalledOnce()
    expect(wsStore.connect).toHaveBeenCalledOnce()
  })

  it('is a no-op on web build (isNative returns false)', async () => {
    isNativeMock.mockReturnValue(false)
    const { setupAppStateListeners } = await import('../src/lib/nativeApp.js')
    const wsStore = { connect: vi.fn(), disconnect: vi.fn() }
    await setupAppStateListeners(wsStore)
    expect(mockAddListener).not.toHaveBeenCalled()
  })
})
