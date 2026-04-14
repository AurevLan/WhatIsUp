/**
 * Biometric authentication helper for the Capacitor native builds.
 *
 * Stores the refresh token in the native secure storage (iOS Keychain /
 * Android Keystore-backed SharedPreferences) and gates its retrieval
 * behind a biometric prompt (Face ID / Touch ID / Android BiometricPrompt).
 *
 * On web builds every function either returns `false` or is a no-op, so
 * callers can import unconditionally without `isNative()` guards.
 */

import { isNative } from './serverConfig'

const FLAG_KEY = 'whatisup_biometric_enabled'
const SECURE_REFRESH_KEY = 'whatisup_refresh_token'

async function _lazyBiometric() {
  const mod = await import('@capgo/capacitor-native-biometric')
  return mod.NativeBiometric
}

async function _lazySecureStorage() {
  const mod = await import('capacitor-secure-storage-plugin')
  return mod.SecureStoragePlugin
}

/**
 * True when the device is a native Capacitor build AND has biometric
 * hardware enrolled. Safe to call on the web — returns false.
 */
export async function isBiometricAvailable() {
  if (!isNative()) return false
  try {
    const NativeBiometric = await _lazyBiometric()
    const result = await NativeBiometric.isAvailable()
    return result.isAvailable === true
  } catch {
    return false
  }
}

/** True when the user has opted in to biometric unlock. */
export function isBiometricEnabled() {
  return localStorage.getItem(FLAG_KEY) === '1'
}

/**
 * Prompt the user for biometric authentication and, on success, persist the
 * refresh token to secure storage. Returns true on success, false on cancel
 * or error. Safe to call on the web (returns false immediately).
 */
export async function enableBiometric(refreshToken, { reason } = {}) {
  if (!isNative()) return false
  if (!refreshToken) return false
  try {
    const NativeBiometric = await _lazyBiometric()
    await NativeBiometric.verifyIdentity({
      reason: reason || 'Unlock WhatIsUp',
      title: 'Enable biometric unlock',
      subtitle: 'Use Face ID / fingerprint to sign in next time',
    })
    const SecureStoragePlugin = await _lazySecureStorage()
    await SecureStoragePlugin.set({ key: SECURE_REFRESH_KEY, value: refreshToken })
    localStorage.setItem(FLAG_KEY, '1')
    return true
  } catch {
    return false
  }
}

/**
 * Prompt biometric and, on success, return the stored refresh token.
 * Returns null if the user cancels, hardware fails, or nothing is stored.
 */
export async function unlockRefreshToken({ reason } = {}) {
  if (!isNative()) return null
  if (!isBiometricEnabled()) return null
  try {
    const NativeBiometric = await _lazyBiometric()
    await NativeBiometric.verifyIdentity({
      reason: reason || 'Unlock WhatIsUp',
      title: 'Unlock WhatIsUp',
      subtitle: 'Authenticate to resume your session',
    })
    const SecureStoragePlugin = await _lazySecureStorage()
    const { value } = await SecureStoragePlugin.get({ key: SECURE_REFRESH_KEY })
    return value || null
  } catch {
    return null
  }
}

/** Wipe the stored refresh token and clear the opt-in flag. */
export async function disableBiometric() {
  localStorage.removeItem(FLAG_KEY)
  if (!isNative()) return
  try {
    const SecureStoragePlugin = await _lazySecureStorage()
    await SecureStoragePlugin.remove({ key: SECURE_REFRESH_KEY })
  } catch {
    // Nothing to clean up — ignore.
  }
}

/**
 * Keep the secure-storage copy of the refresh token in sync after a
 * successful refresh. No-op when biometric unlock is not enabled.
 */
export async function syncRefreshToken(refreshToken) {
  if (!isNative()) return
  if (!isBiometricEnabled()) return
  if (!refreshToken) return
  try {
    const SecureStoragePlugin = await _lazySecureStorage()
    await SecureStoragePlugin.set({ key: SECURE_REFRESH_KEY, value: refreshToken })
  } catch {
    // If secure storage fails we silently keep the localStorage copy —
    // the user will be asked for biometrics again next time.
  }
}
