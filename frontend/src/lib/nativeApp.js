// Native app lifecycle listeners via @capacitor/app.
//
// Every exported function is a no-op on the web build — the isNative() guard
// ensures Capacitor plugins are never imported in non-native contexts. The
// dynamic import is intentional so the plugin is only pulled in when actually
// needed, keeping the web bundle free of native-only code.

import { isNative } from './serverConfig'

async function _loadApp() {
  try {
    const { App } = await import('@capacitor/app')
    return App
  } catch {
    return null
  }
}

let _backButtonWired = false
let _appStateListenersWired = false

/**
 * Register the Android hardware back button (no-op on web).
 *
 * Capacitor's `backButton` event carries `{ canGoBack: boolean }` — the plugin
 * probes the WebView history stack. We mirror that to Vue Router:
 *   - canGoBack → router.back()
 *   - at root   → App.exitApp() (exits the app as the user expects)
 *
 * Guarded by a module-level flag: `AppLayout` calls this from onMounted with
 * no matching onUnmounted removal, and views outside the layout (e.g.
 * LoginView) cause it to remount on every logout→login cycle. Without the
 * guard each remount would add another listener, so a single back-press
 * would fire router.back()/exitApp() once per registration.
 */
export async function setupBackButton(router) {
  if (!isNative() || _backButtonWired) return
  const App = await _loadApp()
  if (!App) return
  _backButtonWired = true

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
 *
 * Guarded by a module-level flag — see `setupBackButton` above for why
 * `AppLayout` remounting (e.g. logout→login) would otherwise duplicate the
 * listener and call connect()/disconnect() N times per transition.
 */
export async function setupAppStateListeners(wsStore) {
  if (!isNative() || _appStateListenersWired) return
  const App = await _loadApp()
  if (!App) return
  _appStateListenersWired = true

  App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) {
      wsStore.connect()
    } else {
      wsStore.disconnect()
    }
  })
}
