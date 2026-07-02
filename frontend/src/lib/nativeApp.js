// Native app lifecycle listeners via @capacitor/app.
//
// Every exported function is a no-op on the web build — the isNative() guard
// ensures Capacitor plugins are never imported in non-native contexts. The
// dynamic import is intentional so that bundlers don't tree-shake the plugin
// out and so the web bundle stays free of native-only code.

import { isNative } from './serverConfig'

async function _loadApp() {
  try {
    const { App } = await import('@capacitor/app')
    return App
  } catch {
    return null
  }
}

/**
 * Register the Android hardware back button (no-op on web).
 *
 * Capacitor's `backButton` event carries `{ canGoBack: boolean }` — the plugin
 * probes the WebView history stack. We mirror that to Vue Router:
 *   - canGoBack → router.back()
 *   - at root   → App.exitApp() (exits the app as the user expects)
 */
export async function setupBackButton(router) {
  if (!isNative()) return
  const App = await _loadApp()
  if (!App) return

  App.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) {
      router.back()
    } else {
      App.exitApp()
    }
  })
}

/**
 * Suspend the WebSocket while the app is in the background; resume on
 * foreground (no-op on web).
 *
 * Uses the same `stopped` mechanism as `wsStore.disconnect()` — no custom flag
 * needed. `connect()` always resets `stopped = false` so a subsequent resume
 * reconnects cleanly. The store's `connect()` is already a no-op when
 * localStorage has no `access_token`, so this is safe even when logged out.
 */
export async function setupAppStateListeners(wsStore) {
  if (!isNative()) return
  const App = await _loadApp()
  if (!App) return

  App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) {
      wsStore.connect()
    } else {
      wsStore.disconnect()
    }
  })
}
