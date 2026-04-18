import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import { apiBaseUrl, isNative } from '../lib/serverConfig'
import api from '../api/client'
import {
  disableBiometric,
  isBiometricAvailable,
  isBiometricEnabled,
  syncRefreshToken,
  unlockRefreshToken,
} from '../lib/biometricAuth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const accessToken = ref(localStorage.getItem('access_token') || null)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isSuperadmin = computed(() => user.value?.is_superadmin ?? false)

  function _isTokenExpired(token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.exp && payload.exp * 1000 < Date.now()
    } catch { return true }
  }

  async function _refreshAccess() {
    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) return false
    try {
      const { data } = await axios.post(`${apiBaseUrl()}/auth/refresh`, { refresh_token: refresh })
      accessToken.value = data.access_token
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      // Keep the secure-storage copy in sync so biometric unlock stays valid.
      await syncRefreshToken(data.refresh_token)
      return true
    } catch {
      return false
    }
  }

  async function _tryBiometricUnlock() {
    if (!isNative() || !isBiometricEnabled()) return false
    const storedRefresh = await unlockRefreshToken()
    if (!storedRefresh) return false
    // Seed localStorage with the unlocked refresh so _refreshAccess() picks it up.
    localStorage.setItem('refresh_token', storedRefresh)
    return await _refreshAccess()
  }

  async function init() {
    // On native, if the user enabled biometric unlock, try that path first —
    // even if no localStorage tokens are present (they may have been cleared
    // between app launches while the secure-storage copy survives).
    if (!accessToken.value && !localStorage.getItem('refresh_token')) {
      const unlocked = await _tryBiometricUnlock()
      if (!unlocked) return
    } else if (!accessToken.value || _isTokenExpired(accessToken.value)) {
      // Standard web / non-biometric path: rotate the expired access token
      // via the stored refresh token BEFORE touching any protected endpoint.
      // Only a failed refresh logs the user out.
      const ok = await _refreshAccess()
      if (!ok) {
        await logout()
        return
      }
    }

    try {
      // Use the shared api client so the 401 interceptor picks up any
      // remaining edge cases (e.g. token revoked between refresh and /me).
      const { data } = await api.get('/auth/me')
      user.value = data
    } catch {
      await logout()
    }
  }

  async function login(email, password) {
    const form = new URLSearchParams({ username: email, password })
    const { data } = await api.post('/auth/login', form)
    accessToken.value = data.access_token
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)

    // Fetch user info — token is now in localStorage so the api interceptor adds it
    const { data: me } = await api.get('/auth/me')
    user.value = me
  }

  async function logout() {
    const refresh = localStorage.getItem('refresh_token')
    if (refresh) {
      try {
        await axios.post(`${apiBaseUrl()}/auth/logout`, { refresh_token: refresh })
      } catch {}
    }
    user.value = null
    accessToken.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    // Also drop the biometric-secured copy — the server-side refresh token
    // has just been revoked, keeping the local copy would be useless.
    await disableBiometric()
  }

  return {
    user,
    accessToken,
    isAuthenticated,
    isSuperadmin,
    init,
    login,
    logout,
    // Re-export for the Settings UI and the post-login opt-in prompt.
    isBiometricAvailable,
    isBiometricEnabled,
  }
})
